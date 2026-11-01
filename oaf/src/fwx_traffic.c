// SPDX-License-Identifier: GPL-2.0-or-later
#include <linux/etherdevice.h>
#include <linux/jhash.h>
#include <linux/kernel.h>
#include <linux/list.h>
#include <linux/math64.h>
#include <linux/random.h>
#include <linux/spinlock.h>
#include <linux/jiffies.h>
#include <linux/types.h>

#include "fwx.h"
#include "fwx_traffic.h"

#define AF_TRAFFIC_GROUPS 128
#define AF_TRAFFIC_HASH_SIZE 128
#define AF_TRAFFIC_CATEGORIES 65
#define AF_TRAFFIC_BATCH_ITEMS 4
#define AF_TRAFFIC_REPORT_BATCHES 64
#define AF_TRAFFIC_RETRY_SECONDS 5
#define AF_TRAFFIC_SIGNED_MAX 0x7fffffffffffffffULL

#define AF_TRAFFIC_GAP_UNATTRIBUTED (1U << 0)
#define AF_TRAFFIC_GAP_BUFFER_FULL (1U << 1)
#define AF_TRAFFIC_GAP_COUNTER_OVERFLOW (1U << 2)
#define AF_TRAFFIC_GAP_INVALID_CLOCK (1U << 3)

struct af_traffic_item {
	u64 up_bytes;
	u64 down_bytes;
	unsigned int app_id;
};

struct af_traffic_group {
	struct hlist_node hash_node;
	/* Each group is on either the free list or the pending list. */
	struct list_head queue;
	u64 bucket_start;
	unsigned char mac[ETH_ALEN];
	unsigned int pending_items;
	unsigned int cursor;
	/* Slot zero is permanently reserved for exact unknown byte counts. */
	struct af_traffic_item items[AF_TRAFFIC_CATEGORIES];
};

struct af_traffic_batch {
	bool valid;
	bool awaiting_ack;
	unsigned int item_count;
	unsigned int capture_gaps;
	u64 seq;
	u64 bucket_start;
	unsigned long retry_at;
	unsigned char mac[ETH_ALEN];
	char boot_id[33];
	struct af_traffic_item items[AF_TRAFFIC_BATCH_ITEMS];
	uint16_t payload_len;
	char payload[MAX_FWX_NL_MSG_LEN];
};

static DEFINE_SPINLOCK(af_traffic_lock);
static struct af_traffic_group af_traffic_groups[AF_TRAFFIC_GROUPS];
static struct hlist_head af_traffic_hash[AF_TRAFFIC_HASH_SIZE];
static LIST_HEAD(af_traffic_free);
static LIST_HEAD(af_traffic_pending);
static unsigned int af_traffic_capture_gaps;
static bool af_traffic_ready;

/* Maintenance reporting and ACK handling share af_traffic_lock for the
 * staged batch and IDs. A snapshot owns its bytes independently of recycled
 * active groups. */
static struct af_traffic_batch af_traffic_staged;
static unsigned char af_traffic_boot_bytes[16];
static char af_traffic_boot_id[33];
static u64 af_traffic_seq;

int af_send_msg_to_user(char *pbuf, uint16_t len);

static void af_traffic_new_boot_id(void)
{
	static const char hex[] = "0123456789abcdef";
	unsigned char bytes[sizeof(af_traffic_boot_bytes)];
	unsigned int i;

	/* Generate a fresh accounting incarnation on every initialization and
	 * signed-sequence rollover, not a system-boot ID reused across reloads. */
	get_random_bytes(bytes, sizeof(bytes));
	if (!memcmp(bytes, af_traffic_boot_bytes, sizeof(bytes)))
		bytes[0] ^= 0x01;
	memcpy(af_traffic_boot_bytes, bytes, sizeof(bytes));
	for (i = 0; i < sizeof(bytes); i++) {
		af_traffic_boot_id[i * 2] = hex[bytes[i] >> 4];
		af_traffic_boot_id[i * 2 + 1] = hex[bytes[i] & 0x0f];
	}
	af_traffic_boot_id[32] = '\0';
	af_traffic_seq = 0;
}

static struct af_traffic_group *
af_traffic_group_locked(const unsigned char *mac, u64 bucket_start)
{
	struct af_traffic_group *group;
	unsigned int hash;

	hash = jhash(mac, ETH_ALEN,
		     (u32)bucket_start ^ (u32)(bucket_start >> 32)) &
	       (AF_TRAFFIC_HASH_SIZE - 1);
	hlist_for_each_entry(group, &af_traffic_hash[hash], hash_node) {
		if (group->bucket_start == bucket_start &&
		    !memcmp(group->mac, mac, ETH_ALEN))
			return group;
	}

	if (list_empty(&af_traffic_free)) {
		/* Never evict an old hour or another MAC's unsent bytes. */
		af_traffic_capture_gaps |= AF_TRAFFIC_GAP_BUFFER_FULL;
		return NULL;
	}

	group = list_first_entry(&af_traffic_free, struct af_traffic_group,
				 queue);
	/* Free groups have no counters or category identities left to clear. */
	memcpy(group->mac, mac, ETH_ALEN);
	group->bucket_start = bucket_start;
	group->cursor = 0;
	hlist_add_head(&group->hash_node, &af_traffic_hash[hash]);
	list_move_tail(&group->queue, &af_traffic_pending);
	return group;
}

static struct af_traffic_item *
af_traffic_item_locked(struct af_traffic_group *group, unsigned int app_id)
{
	struct af_traffic_item *free_item = NULL;
	unsigned int i;

	if (!app_id)
		return &group->items[0];

	for (i = 1; i < AF_TRAFFIC_CATEGORIES; i++) {
		if (group->items[i].app_id == app_id)
			return &group->items[i];
		if (!group->items[i].app_id && !free_item)
			free_item = &group->items[i];
	}
	if (free_item) {
		free_item->app_id = app_id;
		return free_item;
	}

	/* Category pressure loses attribution, not bytes. Unknown is still a
	 * counted quantity, so it does not by itself make capture incomplete. */
	return &group->items[0];
}

void af_traffic_v2_unattributed(int pkt_dir, unsigned int bytes)
{
	(void)pkt_dir;
	if (!bytes)
		return;

	/* There is no schema-safe device bucket for these bytes. Keep a sticky
	 * gap for the next real device batch, never invent a MAC or heartbeat.
	 * If no later valid batch exists, this gap itself remains only in RAM. */
	spin_lock_bh(&af_traffic_lock);
	af_traffic_capture_gaps |= AF_TRAFFIC_GAP_UNATTRIBUTED;
	spin_unlock_bh(&af_traffic_lock);
}

void af_traffic_v2_record(const unsigned char *mac, unsigned int app_id,
			  int pkt_dir, unsigned int bytes)
{
	struct af_traffic_group *group;
	struct af_traffic_item *item;
	time64_t seconds;
	u64 bucket_start;
	u64 *counter;
	bool was_empty;

	if (!bytes)
		return;
	if (!mac || !is_valid_ether_addr(mac) ||
	    (pkt_dir != PKT_DIR_UP && pkt_dir != PKT_DIR_DOWN)) {
		af_traffic_v2_unattributed(pkt_dir, bytes);
		return;
	}

	/* Assign the UTC epoch hour at observation, never at send/retry time. */
	seconds = ktime_get_real_seconds();
	if (seconds < 0) {
		spin_lock_bh(&af_traffic_lock);
		af_traffic_capture_gaps |= AF_TRAFFIC_GAP_INVALID_CLOCK;
		spin_unlock_bh(&af_traffic_lock);
		return;
	}
	bucket_start = div_u64((u64)seconds, 3600) * 3600;
	if (app_id <= 1000 || app_id > 32000)
		app_id = 0;

	spin_lock_bh(&af_traffic_lock);
	group = af_traffic_group_locked(mac, bucket_start);
	if (!group)
		goto unlock;
	item = af_traffic_item_locked(group, app_id);
	counter = pkt_dir == PKT_DIR_UP ? &item->up_bytes : &item->down_bytes;
	if ((u64)bytes > ~(u64)0 - *counter) {
		/* Preserve previous bytes; this entire packet is a visible loss. */
		af_traffic_capture_gaps |= AF_TRAFFIC_GAP_COUNTER_OVERFLOW;
		goto unlock;
	}
	was_empty = !item->up_bytes && !item->down_bytes;
	*counter += bytes;
	if (was_empty)
		group->pending_items++;

unlock:
	spin_unlock_bh(&af_traffic_lock);
}

static bool af_traffic_stage_next(void)
{
	struct af_traffic_batch *batch = &af_traffic_staged;
	struct af_traffic_group *group;
	struct af_traffic_item *active;
	struct af_traffic_item *item;
	unsigned int visited;
	u64 available;

	/* The caller only enters with no previous staged batch. Randomness is
	 * obtained outside the packet-path lock; sequence never wraps numeric. */
	if (af_traffic_seq >= AF_TRAFFIC_SIGNED_MAX)
		af_traffic_new_boot_id();

	spin_lock_bh(&af_traffic_lock);
	if (!af_traffic_ready || batch->valid || list_empty(&af_traffic_pending)) {
		spin_unlock_bh(&af_traffic_lock);
		return false;
	}
	group = list_first_entry(&af_traffic_pending, struct af_traffic_group,
				 queue);
	batch->item_count = 0;
	batch->payload_len = 0;
	batch->awaiting_ack = false;
	batch->retry_at = 0;
	batch->capture_gaps = af_traffic_capture_gaps;
	batch->bucket_start = group->bucket_start;
	memcpy(batch->mac, group->mac, ETH_ALEN);
	memcpy(batch->boot_id, af_traffic_boot_id, sizeof(batch->boot_id));
	batch->seq = ++af_traffic_seq;
	for (visited = 0; visited < AF_TRAFFIC_CATEGORIES &&
	     batch->item_count < AF_TRAFFIC_BATCH_ITEMS; visited++) {
		active = &group->items[group->cursor];
		if (++group->cursor == AF_TRAFFIC_CATEGORIES)
			group->cursor = 0;
		if (!active->up_bytes && !active->down_bytes)
			continue;

		item = &batch->items[batch->item_count++];
		item->app_id = active->app_id;
		item->up_bytes = min_t(u64, active->up_bytes,
				       AF_TRAFFIC_SIGNED_MAX);
		available = AF_TRAFFIC_SIGNED_MAX - item->up_bytes;
		item->down_bytes = min_t(u64, active->down_bytes, available);
		/* Never add the two active u64 counters: their sum may exceed u64.
		 * Each staged item's sum is at most S64_MAX; leftovers stay active. */
		active->up_bytes -= item->up_bytes;
		active->down_bytes -= item->down_bytes;
		if (!active->up_bytes && !active->down_bytes) {
			active->app_id = 0;
			group->pending_items--;
		}
	}
	batch->valid = true;
	if (!group->pending_items) {
		hlist_del_init(&group->hash_node);
		list_move_tail(&group->queue, &af_traffic_free);
	} else {
		/* Both group and category cursors rotate without discarding age. */
		list_move_tail(&group->queue, &af_traffic_pending);
	}
	spin_unlock_bh(&af_traffic_lock);
	return true;
}

/* All format inputs are fixed literals or bounded numeric/hex fields. Every
 * snprintf result is checked, including space for NUL; truncated JSON is never
 * sent. Four items keep even maximum signed values comfortably below 1024. */
#define AF_TRAFFIC_JSON_APPEND(...) do { \
	size_t remaining = sizeof(batch->payload) - length; \
	int written = snprintf(batch->payload + length, remaining, __VA_ARGS__); \
	if (written < 0 || (size_t)written >= remaining) \
		return false; \
	length += written; \
} while (0)

static bool af_traffic_encode_batch(struct af_traffic_batch *batch)
{
	static const struct {
		unsigned int flag;
		const char *name;
	} reasons[] = {
		{ AF_TRAFFIC_GAP_UNATTRIBUTED, "unattributed" },
		{ AF_TRAFFIC_GAP_BUFFER_FULL, "buffer_full" },
		{ AF_TRAFFIC_GAP_COUNTER_OVERFLOW, "counter_overflow" },
		{ AF_TRAFFIC_GAP_INVALID_CLOCK, "invalid_clock" },
	};
	const struct af_traffic_item *item;
	const char *separator = "";
	size_t length = 0;
	unsigned int i;

	AF_TRAFFIC_JSON_APPEND("{\"v\":2,\"type\":\"traffic_delta\","
		"\"mac\":\"" MAC_FMT "\",\"boot_id\":\"%s\",\"seq\":%llu,"
		"\"bucket_start\":%llu,\"coverage\":{\"up\":\"observed\","
		"\"down\":\"observed\"},\"complete\":%s",
		MAC_ARRAY(batch->mac), batch->boot_id,
		(unsigned long long)batch->seq,
		(unsigned long long)batch->bucket_start,
		batch->capture_gaps ? "false" : "true");
	if (batch->capture_gaps) {
		AF_TRAFFIC_JSON_APPEND(",\"coverage_reason\":\"");
		for (i = 0; i < ARRAY_SIZE(reasons); i++) {
			if (!(batch->capture_gaps & reasons[i].flag))
				continue;
			AF_TRAFFIC_JSON_APPEND("%s%s", separator, reasons[i].name);
			separator = ",";
		}
		AF_TRAFFIC_JSON_APPEND("\"");
	}
	AF_TRAFFIC_JSON_APPEND(",\"items\":[");
	for (i = 0; i < batch->item_count; i++) {
		item = &batch->items[i];
		AF_TRAFFIC_JSON_APPEND("%s{\"appid\":%u,\"unknown\":%s,"
			"\"up_bytes\":%llu,\"down_bytes\":%llu}",
			i ? "," : "", item->app_id,
			item->app_id ? "false" : "true",
			(unsigned long long)item->up_bytes,
			(unsigned long long)item->down_bytes);
	}
	AF_TRAFFIC_JSON_APPEND("]}");
	batch->payload_len = length;
	return true;
}

#undef AF_TRAFFIC_JSON_APPEND

#define AF_TRAFFIC_ACK_BOOT_ID_LEN 32

static void af_traffic_ack_skip_ws(const char *data, unsigned int len,
					   unsigned int *pos)
{
	while (*pos < len && (data[*pos] == ' ' || data[*pos] == '\t' ||
			      data[*pos] == '\n' || data[*pos] == '\r'))
		(*pos)++;
}

static int af_traffic_ack_parse_string(const char *data, unsigned int len,
					       unsigned int *pos, char *out,
					       unsigned int out_size)
{
	unsigned int copied = 0;
	char ch;

	if (*pos >= len || data[*pos] != '"')
		return -1;
	(*pos)++;
	while (*pos < len) {
		ch = data[(*pos)++];
		if (ch == '"') {
			if (copied >= out_size)
				return -1;
			out[copied] = '\0';
			return 0;
		}
		/* ACK fields are fixed ASCII tokens; rejecting escapes avoids
		 * accepting multiple spellings of boot_id or type. */
		if ((unsigned char)ch < 0x20 || ch == '\\' ||
		    copied + 1 >= out_size)
			return -1;
		out[copied++] = ch;
	}
	return -1;
}

static int af_traffic_ack_parse_uint(const char *data, unsigned int len,
					     unsigned int *pos, u64 *value)
{
	u64 parsed = 0;
	u64 digit;

	if (*pos >= len || data[*pos] < '0' || data[*pos] > '9')
		return -1;
	if (data[*pos] == '0') {
		(*pos)++;
		if (*pos < len && data[*pos] >= '0' && data[*pos] <= '9')
			return -1;
		*value = 0;
		return 0;
	}
	while (*pos < len && data[*pos] >= '0' && data[*pos] <= '9') {
		digit = data[*pos] - '0';
		if (parsed > (~(u64)0 - digit) / 10)
			return -1;
		parsed = parsed * 10 + digit;
		(*pos)++;
	}
	*value = parsed;
	return 0;
}

static int af_traffic_ack_parse(const char *data, unsigned int len,
					char boot_id[AF_TRAFFIC_ACK_BOOT_ID_LEN + 1],
					u64 *seq)
{
	char key[16];
	char type[16];
	u64 number;
	unsigned int pos = 0;
	bool have_v = false;
	bool have_type = false;
	bool have_boot_id = false;
	bool have_seq = false;

	if (!data || !len)
		return 0;
	af_traffic_ack_skip_ws(data, len, &pos);
	if (pos >= len || data[pos++] != '{')
		return 0;
	af_traffic_ack_skip_ws(data, len, &pos);
	if (pos >= len || data[pos] == '}')
		return 0;

	for (;;) {
		if (af_traffic_ack_parse_string(data, len, &pos, key,
						 sizeof(key)) < 0)
			return 0;
		af_traffic_ack_skip_ws(data, len, &pos);
		if (pos >= len || data[pos++] != ':')
			return 0;
		af_traffic_ack_skip_ws(data, len, &pos);

		if (!strcmp(key, "v")) {
			if (have_v || af_traffic_ack_parse_uint(data, len, &pos,
							 &number) < 0 || number != 2)
				return 0;
			have_v = true;
		} else if (!strcmp(key, "type")) {
			if (have_type || af_traffic_ack_parse_string(data, len, &pos,
							   type, sizeof(type)) < 0 ||
			    strcmp(type, "traffic_ack"))
				return 0;
			have_type = true;
		} else if (!strcmp(key, "boot_id")) {
			if (have_boot_id || af_traffic_ack_parse_string(data, len, &pos,
							   boot_id, AF_TRAFFIC_ACK_BOOT_ID_LEN + 1) < 0)
				return 0;
			have_boot_id = true;
		} else if (!strcmp(key, "seq")) {
			if (have_seq || af_traffic_ack_parse_uint(data, len, &pos,
							 &number) < 0)
				return 0;
			*seq = number;
			have_seq = true;
		} else {
			return 0;
		}

		af_traffic_ack_skip_ws(data, len, &pos);
		if (pos >= len)
			return 0;
		if (data[pos] == '}') {
			pos++;
			break;
		}
		if (data[pos++] != ',')
			return 0;
		af_traffic_ack_skip_ws(data, len, &pos);
		if (pos >= len || data[pos] == '}')
			return 0;
	}

	af_traffic_ack_skip_ws(data, len, &pos);
	if (pos != len || !have_v || !have_type || !have_boot_id || !have_seq ||
		strlen(boot_id) != AF_TRAFFIC_ACK_BOOT_ID_LEN)
		return 0;
	return 1;
}

int af_traffic_v2_handle_ack(const char *data, unsigned int len)
{
	struct af_traffic_batch *batch = &af_traffic_staged;
	char boot_id[AF_TRAFFIC_ACK_BOOT_ID_LEN + 1];
	u64 seq;
	int parsed;

	parsed = af_traffic_ack_parse(data, len, boot_id, &seq);
	if (!parsed)
		return 0;

	spin_lock_bh(&af_traffic_lock);
	if (af_traffic_ready && batch->valid && batch->seq == seq &&
	    !memcmp(batch->boot_id, boot_id, sizeof(batch->boot_id))) {
		/* The snapshot and payload are immutable until this exact ACK. */
		batch->valid = false;
		batch->awaiting_ack = false;
		batch->retry_at = 0;
		batch->item_count = 0;
		batch->payload_len = 0;
	}
	spin_unlock_bh(&af_traffic_lock);
	return 1;
}

void af_traffic_v2_report(void)
{
	struct af_traffic_batch *batch = &af_traffic_staged;
	unsigned int sent;
	uint16_t payload_len;
	u64 seq;
	bool encode_failed;
	bool retired;
	bool valid;
	int ret;

	for (sent = 0; sent < AF_TRAFFIC_REPORT_BATCHES; sent++) {
		spin_lock_bh(&af_traffic_lock);
		valid = af_traffic_ready && batch->valid;
		spin_unlock_bh(&af_traffic_lock);
		if (!valid && !af_traffic_stage_next())
			return;

		spin_lock_bh(&af_traffic_lock);
		if (!af_traffic_ready) {
			spin_unlock_bh(&af_traffic_lock);
			return;
		}
		if (!batch->valid) {
			spin_unlock_bh(&af_traffic_lock);
			continue;
		}
		encode_failed = !batch->payload_len &&
			!af_traffic_encode_batch(batch);
		if (encode_failed) {
			spin_unlock_bh(&af_traffic_lock);
			/* Keep ownership of the entire snapshot on encoding error. */
			pr_err_ratelimited("oaf traffic v2: refusing oversized JSON; staged bytes retained\n");
			return;
		}
		if (batch->awaiting_ack && time_before(jiffies, batch->retry_at)) {
			spin_unlock_bh(&af_traffic_lock);
			return;
		}
		seq = batch->seq;
		payload_len = batch->payload_len;
		spin_unlock_bh(&af_traffic_lock);

		ret = af_send_msg_to_user(batch->payload, payload_len);

		spin_lock_bh(&af_traffic_lock);
		retired = !batch->valid || batch->seq != seq;
		if (!retired) {
			if (ret < 0) {
				batch->awaiting_ack = false;
				batch->retry_at = 0;
			} else {
				batch->awaiting_ack = true;
				batch->retry_at = jiffies +
					AF_TRAFFIC_RETRY_SECONDS * HZ;
			}
		}
		spin_unlock_bh(&af_traffic_lock);
		if (ret < 0 || !retired)
			return;
	}
}

void af_traffic_v2_init(void)
{
	unsigned int i;

	/* The netlink socket is created before the client work starts. Keep the
	 * static lock initialized for early callbacks and publish readiness only
	 * after every RAM container has been reset. */
	spin_lock_bh(&af_traffic_lock);
	af_traffic_ready = false;
	spin_unlock_bh(&af_traffic_lock);
	af_traffic_new_boot_id();

	spin_lock_bh(&af_traffic_lock);
	INIT_LIST_HEAD(&af_traffic_free);
	INIT_LIST_HEAD(&af_traffic_pending);
	memset(af_traffic_groups, 0, sizeof(af_traffic_groups));
	memset(&af_traffic_staged, 0, sizeof(af_traffic_staged));
	af_traffic_capture_gaps = 0;
	for (i = 0; i < AF_TRAFFIC_HASH_SIZE; i++)
		INIT_HLIST_HEAD(&af_traffic_hash[i]);
	for (i = 0; i < AF_TRAFFIC_GROUPS; i++) {
		INIT_HLIST_NODE(&af_traffic_groups[i].hash_node);
		INIT_LIST_HEAD(&af_traffic_groups[i].queue);
		list_add_tail(&af_traffic_groups[i].queue, &af_traffic_free);
	}
	af_traffic_ready = true;
	spin_unlock_bh(&af_traffic_lock);
}
void af_traffic_v2_exit(void)
{
	struct af_traffic_group *group;
	unsigned int pending_groups = 0;
	unsigned int staged_items;

	/* Caller has already removed hooks and cancelled maintenance work. No
	 * teardown send can prove persistence, and no unsent data is evicted. */
	spin_lock_bh(&af_traffic_lock);
	af_traffic_ready = false;
	list_for_each_entry(group, &af_traffic_pending, queue)
		pending_groups++;
	staged_items = af_traffic_staged.valid ?
		af_traffic_staged.item_count : 0;
	spin_unlock_bh(&af_traffic_lock);
	if (pending_groups || staged_items)
		pr_warn("oaf traffic v2: exit with %u pending MAC/hour groups and %u staged items only in RAM; userspace commit was not proven\n",
			pending_groups, staged_items);
}
