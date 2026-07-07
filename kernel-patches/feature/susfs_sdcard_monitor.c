// SPDX-License-Identifier: GPL-2.0-only
/*
 * susfs_sdcard_monitor.c — SDCard monitor for SUSFS v2.2.0
 *
 * Adapted for Linux 4.19:
 *   - handle_event instead of handle_inode_event (5.1+)
 *   - file_name is const unsigned char * (c-string), not const struct qstr *
 *   - fsnotify_alloc_group single argument
 *   - override_creds(ksu_cred) instead of setup_selinux()
 *
 * Ported from simonpunk/susfs4ksu gki-android14-6.1 branch.
 */

#include <linux/kthread.h>
#include <linux/workqueue.h>
#include <linux/delay.h>
#include <linux/jump_label.h>
#include <linux/fsnotify_backend.h>
#include <linux/namei.h>
#include <linux/cred.h>
#include <linux/slab.h>
#include <linux/printk.h>
#include <linux/atomic.h>
#include <linux/module.h>

#ifdef CONFIG_KSU_SUSFS

#define SDCARD_ANDROID_PATH "/data/media/0/Android"
DEFINE_STATIC_KEY_TRUE(susfs_is_sdcard_android_data_not_decrypted);

struct watch_dir {
	const char *path;
	u32 mask;
	struct path kpath;
	struct inode *inode;
	struct fsnotify_mark *mark;
};

static struct fsnotify_group *g;

static struct watch_dir g_watch = {
	.path = "/data/media/0",
	.mask = (FS_EVENT_ON_CHILD | FS_ISDIR | FS_OPEN_PERM),
};

static unsigned long sdcard_cleanup_scheduled;
static struct delayed_work sdcard_cleanup_dwork;

extern struct cred *ksu_cred;

static int add_mark_on_inode(struct inode *inode, u32 mask,
			     struct fsnotify_mark **out);

static void susfs_sdcard_cleanup_fn(struct work_struct *work)
{
	struct fsnotify_group *grp;
	struct inode *inode;

	if (static_key_enabled(&susfs_is_sdcard_android_data_not_decrypted))
		static_branch_disable(&susfs_is_sdcard_android_data_not_decrypted);
	pr_info("susfs: /sdcard is decrypted\n");

	grp = xchg(&g, NULL);
	if (grp)
		fsnotify_destroy_group(grp);

	inode = xchg(&g_watch.inode, NULL);
	if (inode)
		iput(inode);

	if (g_watch.kpath.mnt) {
		path_put(&g_watch.kpath);
		memset(&g_watch.kpath, 0, sizeof(g_watch.kpath));
	}
}

static int watch_one_dir(struct watch_dir *wd)
{
	int ret = kern_path(wd->path, LOOKUP_FOLLOW, &wd->kpath);
	if (ret) {
		pr_info("susfs: path not ready: %s (%d)\n", wd->path, ret);
		return ret;
	}
	wd->inode = d_backing_inode(wd->kpath.dentry);
	if (!wd->inode) {
		pr_err("susfs: wd->inode is NULL\n");
		path_put(&wd->kpath);
		return -ENOENT;
	}
	ihold(wd->inode);

	ret = add_mark_on_inode(wd->inode, wd->mask, &wd->mark);
	if (ret) {
		pr_err("susfs: add mark failed for %s (%d)\n", wd->path, ret);
		iput(wd->inode);
		wd->inode = NULL;
		path_put(&wd->kpath);
		return ret;
	}
	pr_info("susfs: watching %s\n", wd->path);
	return 0;
}

/*
 * OnePlus 4.19 (lineage-20) handle_event callback signature.
 * Uses iter_info instead of inode_mark/vfsmount_mark (backported from 5.1+).
 */
static int susfs_handle_sdcard_event(struct fsnotify_group *group,
				     struct inode *inode,
				     u32 mask, const void *data, int data_type,
				     const unsigned char *file_name, u32 cookie,
				     struct fsnotify_iter_info *iter_info)
{
	if (!file_name || strncmp(file_name, "Android", 7))
		return 0;

	if (test_and_set_bit(0, &sdcard_cleanup_scheduled))
		return 0;

	pr_info("susfs: '%s' detected, mask: 0x%x\n", SDCARD_ANDROID_PATH, mask);
	pr_info("susfs: deferring cleanup for 5 seconds\n");
	queue_delayed_work(system_unbound_wq, &sdcard_cleanup_dwork, 5 * HZ);
	return 0;
}

static const struct fsnotify_ops fsnotify_ops = {
	.handle_event = susfs_handle_sdcard_event,
};

static int add_mark_on_inode(struct inode *inode, u32 mask,
			     struct fsnotify_mark **out)
{
	struct fsnotify_mark *m;

	m = kzalloc(sizeof(*m), GFP_KERNEL);
	if (!m)
		return -ENOMEM;

	fsnotify_init_mark(m, g);
	m->mask = mask;

	if (fsnotify_add_inode_mark(m, inode, 0)) {
		fsnotify_put_mark(m);
		return -EINVAL;
	}
	*out = m;
	return 0;
}

static int susfs_sdcard_monitor_fn(void *data)
{
	const struct cred *old_cred;
	int ret = 0;

	old_cred = override_creds(ksu_cred);

	pr_info("susfs: start monitoring path '%s' using fsnotify\n",
		SDCARD_ANDROID_PATH);

	INIT_DELAYED_WORK(&sdcard_cleanup_dwork, susfs_sdcard_cleanup_fn);

	g = fsnotify_alloc_group(&fsnotify_ops);
	if (IS_ERR(g)) {
		pr_err("susfs: fsnotify_alloc_group failed\n");
		revert_creds(old_cred);
		return PTR_ERR(g);
	}

	ret = watch_one_dir(&g_watch);
	if (ret) {
		pr_info("susfs: watch_one_dir returned %d, cleaning up\n", ret);
		fsnotify_destroy_group(g);
		g = NULL;
	}

	revert_creds(old_cred);
	return ret;
}

void susfs_start_sdcard_monitor_fn(void)
{
	struct task_struct *task;

	task = kthread_run(susfs_sdcard_monitor_fn, NULL,
			   "susfs_sdcard_monitor");
	if (IS_ERR(task)) {
		pr_err("susfs: failed to create thread susfs_sdcard_monitor\n");
		pr_info("susfs: /sdcard is forcibly set decrypted\n");
		if (static_key_enabled(&susfs_is_sdcard_android_data_not_decrypted))
			static_branch_disable(&susfs_is_sdcard_android_data_not_decrypted);
	}
}
EXPORT_SYMBOL(susfs_start_sdcard_monitor_fn);

/* Start the sdcard monitor automatically after all module inits */
static int __init susfs_sdcard_monitor_init(void)
{
	susfs_start_sdcard_monitor_fn();
	return 0;
}
late_initcall(susfs_sdcard_monitor_init);

#endif /* CONFIG_KSU_SUSFS */
