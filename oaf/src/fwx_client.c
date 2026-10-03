// SPDX-License-Identifier: GPL-2.0-or-later
/* 
 * Copyright(c) 2026 destan19(TT) <www.fanchmwrt.com>  
*/

#include <linux/init.h>
#include <linux/module.h>
#include <linux/version.h>
#include <net/tcp.h>
#include <linux/netfilter.h>
#include <net/netfilter/nf_conntrack.h>
#include <net/netfilter/nf_conntrack_acct.h>
#include <linux/skbuff.h>
#include <net/ip.h>
#include <linux/types.h>
#include <net/sock.h>
#include <linux/etherdevice.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/list.h>
#include <linux/netfilter_ipv6.h>
#include <linux/ipv6.h>
#include <linux/in6.h>
#include <linux/sort.h>
#include <linux/spinlock.h>
#include <linux/string.h>
#include <linux/errno.h>
#include <linux/rcupdate.h>
#include <linux/rculist.h>
#include <linux/workqueue.h>
#include <linux/jiffies.h>

#include "fwx_client.h"
#include "fwx_client_fs.h"
#include "fwx_log.h"
#include "fwx_mac.h"
#include "fwx_mac_filter.h"
#include "fwx_utils.h"
#include "fwx.h"
#include "k_json.h"

DEFINE_RWLOCK(af_client_lock);

u32 total_client = 0;
struct list_head af_client_list_table[MAX_AF_CLIENT_HASH_SIZE];

static void af_client_maint_work_func(struct work_struct *work);
static DECLARE_DELAYED_WORK(af_client_maint_work, af_client_maint_work_func);
static DEFINE_SPINLOCK(af_client_maint_state_lock);
static bool af_client_stopping;

int g_max_app_report_count = 3;
int g_min_http_match_count = 3;

static DEFINE_RWLOCK(record_whitelist_lock);
#define record_whitelist_read_lock() read_lock_bh(&record_whitelist_lock);
#define record_whitelist_read_unlock() read_unlock_bh(&record_whitelist_lock);
#define record_whitelist_write_lock() write_lock_bh(&record_whitelist_lock);
#define record_whitelist_write_unlock() write_unlock_bh(&record_whitelist_lock);
static mac_config_t g_record_whitelist;


int af_send_msg_to_user(char *pbuf, uint16_t len);
extern char *ipv6_to_str(const struct in6_addr *addr, char *str);


static int is_client_mac_filter_blocked(af_client_info_t *node)
{
	if (!node || !g_mac_filter_enable) {
		return 0;
	}

	if (fwx_match_mac_filter_whitelist(node->mac)) {
		return 0;
	}

	return fwx_match_mac_filter_rule(node->mac, NULL);
}

int fwx_match_record_whitelist(const unsigned char *mac)
{
	struct mac_node *node;
	int ret = 0;

	record_whitelist_read_lock();
	node = fwx_find_mac_node(&g_record_whitelist, mac);
	ret = (node != NULL);
	record_whitelist_read_unlock();

	return ret;
}

static void fwx_sync_record_whitelist_clients(void)
{
	int i;
	af_client_info_t *node = NULL;

	AF_CLIENT_LOCK_W();
	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
	{
		list_for_each_entry(node, &af_client_list_table[i], hlist)
		{
			node->record_whitelist = fwx_match_record_whitelist(node->mac);
		}
	}
	AF_CLIENT_UNLOCK_W();
}

int fwx_set_record_whitelist(const char *mac_list_str)
{
	char mac_buf[1024] = {0};
	char *token = NULL;
	char *save_ptr = NULL;
	u8 mac_bin[ETH_ALEN];
	struct mac_node *node = NULL;

	if (!mac_list_str) {
		return -1;
	}

	if (strscpy(mac_buf, mac_list_str, sizeof(mac_buf)) < 0)
		return -E2BIG;

	record_whitelist_write_lock();
	fwx_flush_mac_list(&g_record_whitelist);
	save_ptr = mac_buf;
	while ((token = strsep(&save_ptr, ",")) != NULL) {
		token = strim(token);
		if (!token || token[0] == '\0') {
			continue;
		}
		if (!mac_str_to_bin(token, mac_bin)) {
			continue;
		}
		node = fwx_find_mac_node(&g_record_whitelist, mac_bin);
		if (!node) {
			fwx_add_mac_node(&g_record_whitelist, mac_bin);
		}
	}
	record_whitelist_write_unlock();

	fwx_sync_record_whitelist_clients();
	return 0;
}


static void
nf_client_list_init(void)
{
	int i;
	AF_CLIENT_LOCK_W();
	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
	{
		INIT_LIST_HEAD(&af_client_list_table[i]);
	}
	fwx_mac_config_init(&g_record_whitelist);
	AF_CLIENT_UNLOCK_W();
	AF_INFO("client list init......ok\n");
}

static void free_visit_info_all(af_client_info_t *p)
{
	struct hlist_head *head;
	struct hlist_node *n;
	app_visit_info_t *info;
	int j;

	spin_lock_bh(&p->visit_info_lock);
	for (j = 0; j < MAX_VISIT_INFO_HASH_SIZE; j++) {
		head = &p->visit_info_hash[j];
		hlist_for_each_entry_safe(info, n, head, hlist) {
			hlist_del(&info->hlist);
			kfree(info);
		}
	}
	spin_unlock_bh(&p->visit_info_lock);
}

static void af_client_detach_all(struct list_head *detached)
{
	af_client_info_t *node;
	int i;

	/* Worker is drained before detaching; hook readers have exited. */
	AF_CLIENT_LOCK_W();
	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
	{
		while (!list_empty(&af_client_list_table[i]))
		{
			node = list_first_entry(&af_client_list_table[i], af_client_info_t, hlist);
			list_del_rcu(&node->hlist);
			list_add(&node->hlist, detached);
		}
	}
	total_client = 0;
	AF_CLIENT_UNLOCK_W();
}

static void af_client_free_detached(struct list_head *detached)
{
	af_client_info_t *node, *tmp;

	/* The work item is drained; no client pointer remains in flight. */
	list_for_each_entry_safe(node, tmp, detached, hlist)
	{
		AF_DEBUG("clean mac:" MAC_FMT "\n", MAC_ARRAY(node->mac));
		remove_client_proc_dir(node);
		free_visit_info_all(node);
		list_del(&node->hlist);
		kfree(node);
	}
	record_whitelist_write_lock();
	fwx_flush_mac_list(&g_record_whitelist);
	record_whitelist_write_unlock();
}

void af_client_list_reset_report_num(void)
{
	int i;
	af_client_info_t *node = NULL;
	AF_CLIENT_LOCK_W();
	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
	{
		list_for_each_entry(node, &af_client_list_table[i], hlist)
		{
			node->report_count = 0;
		}
	}
	AF_CLIENT_UNLOCK_W();
}

int get_mac_hash_code(unsigned char *mac)
{
	if (!mac)
		return 0;
	else
		return mac[5] & (MAX_AF_CLIENT_HASH_SIZE - 1);
}

af_client_info_t *find_af_client(unsigned char *mac)
{
	af_client_info_t *node;
	unsigned int index;

	index = get_mac_hash_code(mac);
	list_for_each_entry(node, &af_client_list_table[index], hlist)
	{
		if (0 == memcmp(node->mac, mac, 6))
		{
			return node;
		}
	}
	return NULL;
}	

af_client_info_t *find_and_add_af_client(unsigned char *mac)
{
	af_client_info_t *nfc;
	nfc = find_af_client(mac);
	if (!nfc){
		nfc = nf_client_add(mac);
	}
	return nfc;
}	


af_client_info_t *find_af_client_by_ip(unsigned int ip)
{
	af_client_info_t *node;
	int i;

	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
	{
		list_for_each_entry(node, &af_client_list_table[i], hlist)
		{
			if (node->ip == ip)
			{
				AF_LMT_DEBUG("match node->ip=%pI4, ip=%pI4\n", &node->ip, &ip);
				return node;
			}
		}
	}
	return NULL;
}
af_client_info_t *find_af_client_by_ipv6(struct in6_addr *ipv6)
{
	af_client_info_t *node;
	int i;
	char addr_str[64] = {0};

	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
	{
		list_for_each_entry(node, &af_client_list_table[i], hlist)
		{
			if (ipv6_addr_equal(&node->ipv6, ipv6))
			{
				AF_INFO("match node->ipv6=%s\n", ipv6_to_str(&node->ipv6, addr_str));
				return node;
			}
		}
	}
	return NULL;
}

af_client_info_t *
nf_client_add(unsigned char *mac)
{
	af_client_info_t *node;
	int index = 0;
	node = (af_client_info_t *)kmalloc(sizeof(af_client_info_t), GFP_ATOMIC);
	if (node == NULL)
	{
		AF_ERROR("kmalloc failed\n");
		return NULL;
	}

	memset(node, 0, sizeof(af_client_info_t));
	memcpy(node->mac, mac, MAC_ADDR_LEN);
	node->record_whitelist = fwx_match_record_whitelist(node->mac);

	node->create_jiffies = jiffies;
	node->update_jiffies = jiffies;
	node->timer_count = 0;
	INIT_LIST_HEAD(&node->maint_list);
	spin_lock_init(&node->visit_info_lock);
	{
		int i;
		for (i = 0; i < MAX_VISIT_INFO_HASH_SIZE; i++) {
			INIT_HLIST_HEAD(&node->visit_info_hash[i]);
		}
	}
	index = get_mac_hash_code(mac);

	AF_LMT_INFO("new client mac=" MAC_FMT "\n", MAC_ARRAY(node->mac));
	total_client++;
	list_add_rcu(&(node->hlist), &af_client_list_table[index]);
	return node;
}




static void af_client_rcu_free(struct rcu_head *rcu)
{
	af_client_info_t *node = container_of(rcu, af_client_info_t, rcu);
	free_visit_info_all(node);
	kfree(node);
}

static void collect_expired_clients(struct list_head *expired)
{
	af_client_info_t *node, *tmp;
	int i;

	/* One O(N) sweep; no proc operations while holding the write lock. */
	AF_CLIENT_LOCK_W();
	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
	{
		list_for_each_entry_safe(node, tmp, &af_client_list_table[i], hlist)
		{
			if (!time_after(jiffies, node->update_jiffies +
					MAX_CLIENT_ACTIVE_TIME * HZ))
				continue;
			list_del_rcu(&node->hlist);
			list_add_tail(&node->hlist, expired);
			total_client--;
		}
	}
	AF_CLIENT_UNLOCK_W();
}


static inline int get_app_id_hash_code(unsigned int app_id)
{
	return app_id & (MAX_VISIT_INFO_HASH_SIZE - 1);
}

static app_visit_info_t *find_visit_info(af_client_info_t *node, unsigned int app_id)
{
	struct hlist_head *head;
	app_visit_info_t *info;
	
	head = &node->visit_info_hash[get_app_id_hash_code(app_id)];
	hlist_for_each_entry(info, head, hlist) {
		if (info->app_id == app_id) {
			return info;
		}
	}
	return NULL;
}

app_visit_info_t *get_or_create_visit_info(af_client_info_t *node, unsigned int app_id)
{
	app_visit_info_t *info;
	
	info = find_visit_info(node, app_id);
	if (info) {
		return info;
	}
	
	info = (app_visit_info_t *)kmalloc(sizeof(app_visit_info_t), GFP_ATOMIC);
	if (!info) {
		return NULL;
	}
	
	memset(info, 0, sizeof(app_visit_info_t));
	info->app_id = app_id;
	INIT_HLIST_NODE(&info->hlist);
	
	hlist_add_head(&info->hlist, &node->visit_info_hash[get_app_id_hash_code(app_id)]);
	return info;
}

void check_expired_visit_info(af_client_info_t *node)
{
	int i;
	u_int32_t cur_timep = 0;
	struct hlist_head *head;
	struct hlist_node *n;
	app_visit_info_t *info;
	
	if (!node)
		return;
	
	cur_timep = af_get_timestamp_sec();
	
	spin_lock_bh(&node->visit_info_lock);
	for (i = 0; i < MAX_VISIT_INFO_HASH_SIZE; i++) {
		head = &node->visit_info_hash[i];
		hlist_for_each_entry_safe(info, n, head, hlist) {
			if (cur_timep - info->latest_time > VISIT_INFO_TIMEOUT_SEC) {
				hlist_del(&info->hlist);
				kfree(info);
			}
		}
	}
	spin_unlock_bh(&node->visit_info_lock);
}

struct client_visit_report {
	unsigned int app_id;
	unsigned int latest_action;
	unsigned int total_num;
};

static int compare_visit_info_count(const void *a, const void *b)
{
	const struct client_visit_report *info_a = a;
	const struct client_visit_report *info_b = b;

	if (info_a->total_num > info_b->total_num)
		return -1;
	if (info_a->total_num < info_b->total_num)
		return 1;
	return 0;
}

int __af_visit_info_report(af_client_info_t *node)
{
	unsigned char mac_str[32] = {0};
	unsigned char ip_str[32] = {0};
	struct client_visit_report info_array[MAX_RECORD_APP_NUM];
	struct hlist_head *head;
	app_visit_info_t *info;
	cJSON *visit_obj;
	cJSON *visit_info_array;
	cJSON *root_obj;
	char *out;
	int i, total_count = 0, report_count = 0;

	root_obj = cJSON_CreateObject();
	if (!root_obj)
		return 0;
	visit_info_array = cJSON_CreateArray();
	if (!visit_info_array) {
		cJSON_Delete(root_obj);
		return 0;
	}

	sprintf(mac_str, MAC_FMT, MAC_ARRAY(node->mac));
	sprintf(ip_str, "%pI4", &node->ip);
	cJSON_AddStringToObject(root_obj, "mac", mac_str);
	cJSON_AddStringToObject(root_obj, "ip", ip_str);
	cJSON_AddNumberToObject(root_obj, "app_num", node->visit_app_num);
	cJSON_AddNumberToObject(root_obj, "up_flow", (u32)(node->period_flow.up_bytes >> 10));
	cJSON_AddNumberToObject(root_obj, "down_flow", (u32)(node->period_flow.down_bytes >> 10));
	cJSON_AddNumberToObject(root_obj, "active", node->active);

	/* Only copy values while locked: cJSON uses GFP_KERNEL and may sleep. */
	spin_lock_bh(&node->visit_info_lock);
	for (i = 0; i < MAX_VISIT_INFO_HASH_SIZE; i++) {
		head = &node->visit_info_hash[i];
		hlist_for_each_entry(info, head, hlist) {
			if (!info->total_num)
				continue;
			if (info->is_http && info->conn_count <= g_min_http_match_count) {
				info->total_num = 0;
				continue;
			}
			if (total_count < MAX_RECORD_APP_NUM) {
				info_array[total_count].app_id = info->app_id;
				info_array[total_count].latest_action = info->latest_action;
				info_array[total_count].total_num = info->total_num;
				info->total_num = 0;
				total_count++;
			}
		}
	}
	spin_unlock_bh(&node->visit_info_lock);

	if (total_count) {
		sort(info_array, total_count, sizeof(info_array[0]), compare_visit_info_count, NULL);
		report_count = total_count > g_max_app_report_count ? g_max_app_report_count : total_count;
	}
	for (i = 0; i < report_count; i++) {
		visit_obj = cJSON_CreateObject();
		cJSON_AddNumberToObject(visit_obj, "appid", info_array[i].app_id);
		cJSON_AddNumberToObject(visit_obj, "latest_action", info_array[i].latest_action);
		cJSON_AddItemToArray(visit_info_array, visit_obj);
	}

	cJSON_AddItemToObject(root_obj, "visit_info", visit_info_array);
	out = cJSON_Print(root_obj);
	if (!out) {
		cJSON_Delete(root_obj);
		return 0;
	}
	cJSON_Minify(out);
	node->report_count++;
	af_send_msg_to_user(out, strlen(out));
	cJSON_Delete(root_obj);
	memset(&node->period_flow, 0x0, sizeof(node->period_flow));
	kfree(out);
	return 0;
}

static inline int get_packet_dir(struct net_device *in)
{
	if (strstr(in->name, g_lan_ifname))
	{
		return PKT_DIR_UP;
	}
	else
	{
		return PKT_DIR_DOWN;
	}
}



void af_update_client_status(af_client_info_t *node)
{
	if (node->last_flow.down_bytes > 0){
		node->period_flow.down_bytes += (node->flow.down_bytes - node->last_flow.down_bytes);
	}
	if (node->last_flow.up_bytes > 0){
		node->period_flow.up_bytes += (node->flow.up_bytes - node->last_flow.up_bytes);
	}	
	AF_LMT_DEBUG("period flow down:%llu up: %llu pkg up %d\n", node->period_flow.down_bytes, 
		node->period_flow.up_bytes, node->rate.pkt_up_rate);

	node->rate.up_rate = (node->flow.up_bytes - node->last_flow.up_bytes) >> 1;
	node->rate.down_rate = (node->flow.down_bytes - node->last_flow.down_bytes) >> 1;
	node->rate.pkt_up_rate  = (node->flow.up_pkts - node->last_flow.up_pkts) >> 1;
	node->rate.pkt_down_rate  = (node->flow.down_pkts - node->last_flow.down_pkts) >> 1;

	node->last_flow.up_bytes = node->flow.up_bytes;
	node->last_flow.down_bytes = node->flow.down_bytes;
	node->last_flow.up_pkts  = node->flow.up_pkts;
	node->last_flow.down_pkts = node->flow.down_pkts;

	if (is_client_mac_filter_blocked(node)) {
		node->active = 0;
		node->active_time = 0;
		node->inactive_time = 0;
		return;
	}

	if (node->rate.pkt_down_rate > 20){
		node->active_time++;
		node->inactive_time = 0;
		node->active = 1;
	}
	else{
		node->inactive_time++;
		node->active_time = 0;
		if (node->active && node->inactive_time > 30){
			node->active = 0;
		}
	}
}


#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)
static u_int32_t af_client_hook(void *priv,
								struct sk_buff *skb,
								const struct nf_hook_state *state)
{
#else
static u_int32_t af_client_hook(unsigned int hook,
								struct sk_buff *skb,
								const struct net_device *in,
								const struct net_device *out,
								int (*okfn)(struct sk_buff *))
{
#endif
	struct ethhdr *ethhdr = NULL;
	unsigned char smac[ETH_ALEN];
	af_client_info_t *nfc = NULL;
	int pkt_dir = 0;
	struct iphdr *iph = NULL;
	unsigned int ip = 0;
	struct ipv6hdr *ip6h = NULL;
	enum ip_conntrack_info ctinfo;

	struct nf_conn *ct = nf_ct_get(skb, &ctinfo);
	if (NULL == ct)
		return NF_ACCEPT;
	if (skb->protocol == htons(ETH_P_IPV6) && AF_MODE_GATEWAY != af_work_mode){
		return NF_ACCEPT;
	}

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)
	if (!skb->dev)
		return NF_ACCEPT;

	pkt_dir = get_packet_dir(skb->dev);
#else
	if (!in)
	{
		AF_ERROR("in is NULL\n");
		return NF_ACCEPT;
	}
	pkt_dir = get_packet_dir(in);
#endif

	if (PKT_DIR_UP != pkt_dir)
		return NF_ACCEPT;

	ethhdr = eth_hdr(skb);
	if (ethhdr)
	{
		memcpy(smac, ethhdr->h_source, ETH_ALEN);
	}
	else
	{
		memcpy(smac, &skb->cb[40], ETH_ALEN);
	}


	AF_CLIENT_LOCK_W();
	nfc = find_af_client(smac);
	if (!nfc)
	{
		if (skb->dev)
			AF_DEBUG("from dev:%s %pI4", skb->dev->name, &ip);
		nfc = nf_client_add(smac);
	}

	if (nfc) {
		if (skb->protocol == htons(ETH_P_IP)) {
			iph = ip_hdr(skb);
			if (iph && nfc->ip != iph->saddr) {
				AF_DEBUG("update node " MAC_FMT " ipv4 %pI4--->%pI4\n", 
					MAC_ARRAY(nfc->mac), &nfc->ip, &iph->saddr);
				nfc->ip = iph->saddr;
			}
		}
		else if (skb->protocol == htons(ETH_P_IPV6)) {
			ip6h = ipv6_hdr(skb);
			if (ip6h && !ipv6_addr_equal(&nfc->ipv6, &ip6h->saddr)) {
				nfc->ipv6 = ip6h->saddr;
			}
		}
		nfc->flow.up_bytes += skb->len;
		nfc->flow.up_pkts++;
		nfc->update_jiffies = jiffies;  
	}

	AF_CLIENT_UNLOCK_W();
	
	return NF_ACCEPT;
}



#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)
static u_int32_t af_client_hook2(void *priv,
								 struct sk_buff *skb,
								 const struct nf_hook_state *state)
{
#else
static u_int32_t af_client_hook2(unsigned int hook,
								 struct sk_buff *skb,
								 const struct net_device *in,
								 const struct net_device *out,
								 int (*okfn)(struct sk_buff *))
{
#endif
	struct ethhdr *ethhdr = NULL;
	unsigned char smac[ETH_ALEN];
	af_client_info_t *nfc = NULL;
	int pkt_dir = 0;
	struct iphdr *iph = NULL;
	struct ipv6hdr *ip6h = NULL;
	enum ip_conntrack_info ctinfo;

	struct nf_conn *ct = nf_ct_get(skb, &ctinfo);
	if (ct == NULL)
	{
		return NF_ACCEPT;
	}

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 4, 0)
	if (!skb->dev)
		return NF_ACCEPT;

	pkt_dir = get_packet_dir(skb->dev);
#else
	if (!in)
	{
		AF_ERROR("in is NULL\n");
		return NF_ACCEPT;
	}
	pkt_dir = get_packet_dir(in);
#endif
	if (!skb->dev)
	{
		return NF_ACCEPT;
	}


	if (PKT_DIR_DOWN != pkt_dir)
		return NF_ACCEPT;

	AF_CLIENT_LOCK_R();
	
	if (skb->protocol == htons(ETH_P_IP)) {
		iph = ip_hdr(skb);
		nfc = find_af_client_by_ip(iph->daddr);
	}
	else if (skb->protocol == htons(ETH_P_IPV6)) {
		ip6h = ipv6_hdr(skb);
		nfc = find_af_client_by_ipv6(&ip6h->daddr);
		if (nfc){
			AF_LMT_DEBUG("found ipv6 %pI6 client\n", &ip6h->daddr);
		}
		else{
			AF_LMT_DEBUG("not found ipv6 %pI6 client\n", &ip6h->daddr);
		}
	}
	if (nfc){
		nfc->flow.down_bytes += skb->len;
		nfc->flow.down_pkts++;
		nfc->update_jiffies = jiffies;  
	}

	AF_CLIENT_UNLOCK_R();
	return NF_ACCEPT;
}

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 16, 0)
static struct nf_hook_ops af_client_ops[] = {
	{
		.hook = af_client_hook,
		.pf = NFPROTO_INET,
		.hooknum = NF_INET_FORWARD,
		.priority = NF_IP_PRI_FIRST + 1,
	},
	{
		.hook = af_client_hook2,
		.pf = NFPROTO_INET,
		.hooknum = NF_INET_FORWARD,
		.priority = NF_IP_PRI_LAST - 1,
	},

};
#else
static struct nf_hook_ops af_client_ops[] = {
	{
		.hook = af_client_hook,
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 4, 0)
		.owner = THIS_MODULE,
#endif
		.pf = NFPROTO_IPV4,
		.hooknum = NF_INET_FORWARD,
		.priority = NF_IP_PRI_FIRST + 1,
	},
	{
		.hook = af_client_hook,
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 4, 0)
		.owner = THIS_MODULE,
#endif
		.pf = NFPROTO_IPV6,
		.hooknum = NF_INET_FORWARD,
		.priority = NF_IP_PRI_FIRST + 1,
	},
};
#endif


static void af_client_maint_work_func(struct work_struct *work)
{
	LIST_HEAD(pending);
	LIST_HEAD(expired);
	af_client_info_t *node, *tmp;
	int i;

	/*
	 * Single work item: its per-client list links are private to this
	 * invocation. The exit path cancels it before detaching any client.
	 */
	AF_CLIENT_LOCK_R();
	for (i = 0; i < MAX_AF_CLIENT_HASH_SIZE; i++)
		list_for_each_entry(node, &af_client_list_table[i], hlist)
			list_add_tail(&node->maint_list, &pending);
	AF_CLIENT_UNLOCK_R();

	/* No may-sleep operation runs under af_client_lock. */
	list_for_each_entry_safe(node, tmp, &pending, maint_list)
	{
		list_del_init(&node->maint_list);
		if (!node->proc_dir)
			create_client_proc_dir(node);
		if (node->timer_count >= 30) {
			__af_visit_info_report(node);
			node->timer_count = 0;
		}
		check_expired_visit_info(node);
		af_update_client_status(node);
		node->timer_count++;
	}

	/* A single O(N) expiry sweep, not a fixed-rate cleanup bottleneck. */
	collect_expired_clients(&expired);
	list_for_each_entry_safe(node, tmp, &expired, hlist)
	{
		list_del_init(&node->hlist);
		remove_client_proc_dir(node);
		call_rcu(&node->rcu, af_client_rcu_free);
	}

	/* Serialize the final rearm with af_client_exit's stop decision. */
	spin_lock_bh(&af_client_maint_state_lock);
	if (!af_client_stopping)
		schedule_delayed_work(&af_client_maint_work, 2 * HZ);
	spin_unlock_bh(&af_client_maint_state_lock);
}




int af_client_init(void)
{
	int err;
	nf_client_list_init();
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 3, 0)
	err = nf_register_net_hooks(&init_net, af_client_ops, ARRAY_SIZE(af_client_ops));
#else
	err = nf_register_hooks(af_client_ops, ARRAY_SIZE(af_client_ops));
#endif
	if (err) {
		AF_ERROR("register client hooks failed!\n");
	}
	schedule_delayed_work(&af_client_maint_work, HZ);

	return 0;
}

int fwx_api_add_record_whitelist(cJSON *data_obj)
{
	cJSON *mac_array;
	int i;
	u8 mac_bin[ETH_ALEN];

	if (!data_obj) {
		return -1;
	}

	mac_array = cJSON_GetObjectItem(data_obj, "mac_list");
	if (!mac_array) {
		printk("mac_list not found\n");
		return -1;
	}

	record_whitelist_write_lock();
	for (i = 0; i < cJSON_GetArraySize(mac_array); i++) {
		cJSON *mac_obj = cJSON_GetArrayItem(mac_array, i);
		if (mac_obj && mac_str_to_bin(mac_obj->valuestring, mac_bin)) {
			fwx_add_mac_node(&g_record_whitelist, mac_bin);
		}
	}
	record_whitelist_write_unlock();

	fwx_sync_record_whitelist_clients();
	return 0;
}

int fwx_api_del_record_whitelist(cJSON *data_obj)
{
	cJSON *mac_obj;
	u8 mac_bin[ETH_ALEN];
	struct mac_node *node;

	if (!data_obj) {
		return -1;
	}

	mac_obj = cJSON_GetObjectItem(data_obj, "mac");
	if (!mac_obj) {
		printk("mac not found\n");
		return -1;
	}

	if (!mac_str_to_bin(mac_obj->valuestring, mac_bin)) {
		printk("invalid mac format\n");
		return -1;
	}

	record_whitelist_write_lock();
	node = fwx_find_mac_node(&g_record_whitelist, mac_bin);
	if (node) {
		hlist_del(&node->hlist);
		kfree(node);
		record_whitelist_write_unlock();
		fwx_sync_record_whitelist_clients();
		return 0;
	}
	record_whitelist_write_unlock();
	return -1;
}

int fwx_api_flush_record_whitelist(cJSON *data_obj)
{
	record_whitelist_write_lock();
	fwx_flush_mac_list(&g_record_whitelist);
	record_whitelist_write_unlock();
	fwx_sync_record_whitelist_clients();
	return 0;
}

void af_client_exit(void)
{
	LIST_HEAD(detached);

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 3, 0)
	nf_unregister_net_hooks(&init_net, af_client_ops, ARRAY_SIZE(af_client_ops));
#else
	nf_unregister_hooks(af_client_ops, ARRAY_SIZE(af_client_ops));
#endif
	/*
	 * Prevent the worker from rearming while exit waits. Once cancelled,
	 * unregistered hooks prevent new client creation;
	 * clients remain linked until this drain completes.
	 */
	spin_lock_bh(&af_client_maint_state_lock);
	af_client_stopping = true;
	spin_unlock_bh(&af_client_maint_state_lock);
	cancel_delayed_work_sync(&af_client_maint_work);
	af_client_detach_all(&detached);
	af_client_free_detached(&detached);
	rcu_barrier();
	remove_af_client_base_dir();
	return;
}
