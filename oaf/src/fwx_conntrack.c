// SPDX-License-Identifier: GPL-2.0-or-later
/* 
 * Copyright(c) 2026 destan19(TT) <www.fanchmwrt.com>  
*/
#include <linux/init.h>
#include <linux/module.h>
#include <linux/version.h>
#include <linux/types.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
#include <linux/mutex.h>
#include <linux/list.h>
#include <linux/spinlock.h>
#include <linux/jhash.h>
#include <linux/seq_file.h>
#include <linux/proc_fs.h>
#include <linux/sysctl.h>
#include <net/ip.h>
#include <linux/types.h>
#include <net/sock.h>
#include <linux/etherdevice.h>
#include <linux/cdev.h>
#include "fwx_conntrack.h"
#include "fwx_log.h"
#include "fwx.h"

struct hlist_head af_conn_table[AF_CONN_HASH_SIZE];

DEFINE_SPINLOCK(af_conn_lock);


static u32 af_conn_hash(u32 src_ip, u32 dst_ip, 
                       u16 src_port, u16 dst_port, 
                       u8 protocol)
{
    return jhash_3words(src_ip, dst_ip,
                       ((u32)protocol << 16) | src_port,
                       dst_port) % AF_CONN_HASH_SIZE;
}


void af_conn_cleanup(void)
{
    int i;
    spin_lock(&af_conn_lock);
	af_conn_t *p = NULL;
	struct hlist_node *n;

	for (i = 0; i < AF_CONN_HASH_SIZE; i++)
	{
		hlist_for_each_entry_safe(p, n, &af_conn_table[i], node)
		{
			hlist_del(&p->node);
			kfree(p);
		}
	}
    spin_unlock(&af_conn_lock);
}

af_conn_t *af_conn_add(u32 src_ip, u32 dst_ip, u16 src_port, u16 dst_port, u8 protocol)
{
    u32 hash;
    af_conn_t *conn;
    hash = af_conn_hash(src_ip, dst_ip, src_port, dst_port, protocol);
    conn = kmalloc(sizeof(af_conn_t), GFP_ATOMIC);
    if (!conn) {
        return NULL;
    }
    
    conn->src_ip = src_ip;
    conn->dst_ip = dst_ip;
    conn->src_port = src_port;
    conn->dst_port = dst_port;
    conn->protocol = protocol;
    conn->total_pkts = 0;
    conn->app_id = 0;
	conn->client_hello = 0;
    conn->drop = 0;
    conn->state = AF_CONN_NEW;
    conn->last_jiffies = jiffies;
    hlist_add_head(&conn->node, &af_conn_table[hash]);

    AF_LMT_INFO("add new conn ok...%pI4:%d->%pI4:%d %d\n",
        &conn->src_ip, conn->src_port, &conn->dst_ip, conn->dst_port, conn->protocol);
    return conn;
}


/* Callers must hold af_conn_lock. */
af_conn_t* af_conn_find(u32 src_ip, u32 dst_ip, u16 src_port, u16 dst_port, u8 protocol)
{
    u32 hash;
    af_conn_t *conn;
    
    hash = af_conn_hash(src_ip, dst_ip, src_port, dst_port, protocol);
	hlist_for_each_entry(conn, &af_conn_table[hash], node)
	{
		if (conn->src_ip == src_ip && conn->dst_ip == dst_ip &&
            conn->src_port == src_port && conn->dst_port == dst_port &&
            conn->protocol == protocol) {
            return conn;
        }
	}
    return NULL;
}


/* Callers must hold af_conn_lock. */
af_conn_t* af_conn_find_and_add(u32 src_ip, u32 dst_ip, u16 src_port, u16 dst_port, u8 protocol)
{
    af_conn_t *conn;
    conn = af_conn_find(src_ip, dst_ip, src_port, dst_port, protocol);
    if (!conn)
    {
        conn = af_conn_add(src_ip, dst_ip, src_port, dst_port, protocol);
    }
    return conn;
}


void af_conn_update(af_conn_t *conn, u32 app_id, u8 drop)
{
    spin_lock(&af_conn_lock);
    conn->app_id = app_id;
    conn->drop = drop;
    conn->last_jiffies = jiffies;
    spin_unlock(&af_conn_lock);
}

#define MAX_AF_CONN_CHECK_COUNT 5
void af_conn_clean_timeout(void)
{
    int i;
    af_conn_t *conn;
    struct hlist_node *n;
    unsigned long timeout = AF_CONN_TIMEOUT * HZ;
    static int last_bucket = 0;
    int count = 0;
    spin_lock(&af_conn_lock);
    for (i = last_bucket; i < AF_CONN_HASH_SIZE; i++)
    {
        hlist_for_each_entry_safe(conn, n, &af_conn_table[i], node)
        {
            if (time_after(jiffies, conn->last_jiffies + timeout)) {
                AF_LMT_INFO("clean timeout conn ok...%pI4:%d->%pI4:%d %d\n",
                 &conn->src_ip, conn->src_port, &conn->dst_ip, conn->dst_port, conn->protocol);
                hlist_del(&(conn->node));
                kfree(conn);
            }
        }
        last_bucket = i;
        count++;
        if (count > MAX_AF_CONN_CHECK_COUNT)
            break;
    }
    if (last_bucket == AF_CONN_HASH_SIZE - 1)
    {
        last_bucket = 0;
    }
    spin_unlock(&af_conn_lock);
} 

/* A proc reader owns a bounded copy, not pointers into the live hash table. */
#define AF_CONN_PROC_MAX_BYTES (1U << 20)
#define AF_CONN_PROC_MAX_TOTAL_BYTES (2U << 20)

struct af_conn_snapshot {
    u32 src_ip;
    u32 dst_ip;
    u32 app_id;
    u32 total_pkts;
    u16 src_port;
    u16 dst_port;
    u8 protocol;
    u8 drop;
    unsigned long last_jiffies;
};

struct af_conn_iter_state {
    struct af_conn_snapshot *entries;
    size_t count;
    size_t alloc_bytes;
};

static DEFINE_MUTEX(af_conn_snapshot_mutex);
static size_t af_conn_snapshot_bytes;

static void *af_conn_seq_start(struct seq_file *s, loff_t *pos)
{
    struct af_conn_iter_state *st = s->private;

    if (*pos == 0)
        return SEQ_START_TOKEN;
    if (*pos < 0 || (u64)*pos > st->count)
        return NULL;
    return &st->entries[*pos - 1];
}

static void *af_conn_seq_next(struct seq_file *s, void *v, loff_t *pos)
{
    struct af_conn_iter_state *st = s->private;

    (*pos)++;
    if (*pos < 0 || (u64)*pos > st->count)
        return NULL;
    return &st->entries[*pos - 1];
}

static void af_conn_seq_stop(struct seq_file *s, void *v)
{
}

static int af_conn_seq_show(struct seq_file *s, void *v)
{
    unsigned char src_ip_str[32] = {0};
    unsigned char dst_ip_str[32] = {0};
    const struct af_conn_snapshot *node = v;
    u_int32_t inactive_time;

    if (v == SEQ_START_TOKEN)
    {
        seq_printf(s, "%-4s %-20s %-20s %-12s %-12s %-12s %-12s %-12s %-12s %-12s\n",
        "Id", "src_ip", "dst_ip", "src_port", "dst_port", "protocol", "app_id", "drop", "inactive", "total_pkts");
        return 0;
    }

    sprintf(src_ip_str, "%pI4", &node->src_ip);
    sprintf(dst_ip_str, "%pI4", &node->dst_ip);
    inactive_time = jiffies - node->last_jiffies;

    seq_printf(s, "%-4lld %-20s %-20s %-12d %-12d %-12d %-12d %-12d %-12d %-12d\n", (long long)s->index, src_ip_str, dst_ip_str,
               node->src_port, node->dst_port, node->protocol, node->app_id, node->drop, inactive_time, node->total_pkts);
    return 0;
}
static const struct seq_operations af_conn_seq_ops = {
    .start = af_conn_seq_start,
    .next = af_conn_seq_next,
    .stop = af_conn_seq_stop,
    .show = af_conn_seq_show
};


static int af_conn_open(struct inode *inode, struct file *file)
{
    struct seq_file *seq;
    struct af_conn_iter_state *iter;
    af_conn_t *conn;
    size_t count = 0;
    unsigned int i;
    int err;

    iter = kzalloc(sizeof(*iter), GFP_KERNEL);
    if (!iter)
        return -ENOMEM;

    /* Count in short per-bucket critical sections; never allocate under a spinlock. */
    for (i = 0; i < AF_CONN_HASH_SIZE; i++) {
        spin_lock_bh(&af_conn_lock);
        hlist_for_each_entry(conn, &af_conn_table[i], node) {
            if (count >= AF_CONN_PROC_MAX_BYTES / sizeof(*iter->entries)) {
                spin_unlock_bh(&af_conn_lock);
                err = -E2BIG;
                goto free_iter;
            }
            count++;
        }
        spin_unlock_bh(&af_conn_lock);
    }

    if (count) {
        iter->alloc_bytes = count * sizeof(*iter->entries);
        mutex_lock(&af_conn_snapshot_mutex);
        if (af_conn_snapshot_bytes > AF_CONN_PROC_MAX_TOTAL_BYTES - iter->alloc_bytes) {
            mutex_unlock(&af_conn_snapshot_mutex);
            err = -ENOMEM;
            goto free_iter;
        }
        af_conn_snapshot_bytes += iter->alloc_bytes;
        mutex_unlock(&af_conn_snapshot_mutex);

        iter->entries = vzalloc(iter->alloc_bytes);
        if (!iter->entries) {
            err = -ENOMEM;
            goto release_budget;
        }

        /* Concurrent insertions may be omitted; never retain live table pointers. */
        for (i = 0; i < AF_CONN_HASH_SIZE && iter->count < count; i++) {
            spin_lock_bh(&af_conn_lock);
            hlist_for_each_entry(conn, &af_conn_table[i], node) {
                struct af_conn_snapshot *entry;

                if (iter->count == count)
                    break;
                entry = &iter->entries[iter->count++];
                entry->src_ip = conn->src_ip;
                entry->dst_ip = conn->dst_ip;
                entry->src_port = conn->src_port;
                entry->dst_port = conn->dst_port;
                entry->protocol = conn->protocol;
                entry->app_id = conn->app_id;
                entry->drop = conn->drop;
                entry->total_pkts = conn->total_pkts;
                entry->last_jiffies = conn->last_jiffies;
            }
            spin_unlock_bh(&af_conn_lock);
        }
    }

    err = seq_open(file, &af_conn_seq_ops);
    if (err)
        goto free_snapshot;

    seq = file->private_data;
    seq->private = iter;
    return 0;

free_snapshot:
    vfree(iter->entries);
release_budget:
    if (iter->alloc_bytes) {
        mutex_lock(&af_conn_snapshot_mutex);
        af_conn_snapshot_bytes -= iter->alloc_bytes;
        mutex_unlock(&af_conn_snapshot_mutex);
    }
free_iter:
    kfree(iter);
    return err;
}

static int af_conn_release(struct inode *inode, struct file *file)
{
    struct seq_file *seq = file->private_data;
    struct af_conn_iter_state *iter = seq->private;

    vfree(iter->entries);
    if (iter->alloc_bytes) {
        mutex_lock(&af_conn_snapshot_mutex);
        af_conn_snapshot_bytes -= iter->alloc_bytes;
        mutex_unlock(&af_conn_snapshot_mutex);
    }
    return seq_release_private(inode, file);
}

#if LINUX_VERSION_CODE <= KERNEL_VERSION(5, 5, 0)
static const struct file_operations af_conn_fops = {
    .owner = THIS_MODULE,
    .open = af_conn_open,
    .read = seq_read,
    .llseek = seq_lseek,
    .release = af_conn_release,
};
#else
static const struct proc_ops af_conn_fops = {
    .proc_flags = PROC_ENTRY_PERMANENT,
    .proc_read = seq_read,
    .proc_open = af_conn_open,
    .proc_lseek = seq_lseek,
    .proc_release = af_conn_release,
};
#endif

#define AF_CONN_PROC_STR "af_conn"

int af_conn_init_procfs(void)
{
    struct proc_dir_entry *pde;
    struct net *net = &init_net;
    pde = proc_create(AF_CONN_PROC_STR, 0644, net->proc_net, &af_conn_fops);
    if (!pde)
    {
        printk("af_conn seq file created error\n");
        return -1;
    }

    return 0;
}

void af_conn_remove_procfs(void)
{
    struct net *net = &init_net;
    remove_proc_entry(AF_CONN_PROC_STR, net->proc_net);
}


int af_conn_init(void)
{
    int i;
    for (i = 0; i < AF_CONN_HASH_SIZE; i++)
	{
		INIT_HLIST_HEAD(&af_conn_table[i]);
	}
    af_conn_init_procfs(); 
    return 0;
}

void af_conn_exit(void){
    af_conn_remove_procfs();
    af_conn_cleanup();
}
