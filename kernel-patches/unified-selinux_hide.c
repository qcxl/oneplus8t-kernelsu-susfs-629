// SPDX-License-Identifier: GPL-2.0
/*
 * feature/selinux_hide.c — 统一版 SELinux hide (4.19)
 *
 * 合并版本 A (dev: ksu_patch_text + ksu_lsm_hook + fake_status) 和
 * 版本 B (注入: 过滤模式 + 直接 security_hook_heads 操作) 的最佳部分。
 *
 * 4.19 适配：
 *   - 过滤模式代替 backup_sepolicy (4.19 不支持 struct selinux_policy)
 *   - set_memory_rw/ro 临时可写后写入 write_op[] (WRITE_ONCE 直接写
 *     .rodata 在 CONFIG_STRICT_KERNEL_RWX=y 上触发 page fault)
 *   - 去掉 write_op[SEL_ENFORCE] 钩子 (LineageOS 4.19 恒为 NULL)
 *   - init 时不自动启用 (toggle 才激活)
 *   - Manager UID 豁免 (GHA 工作流中原有的注入步骤, 现内置)
 *   - 新增 KSU_FEATURE_SET_SELINUX_ENFORCE handler (修复 app 侧切换失败)
 */

#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/printk.h>
#include <linux/string.h>
#include <linux/fs.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/proc_fs.h>
#include <linux/kallsyms.h>
#include <linux/lsm_hooks.h>
#include <linux/cred.h>
#include <linux/uaccess.h>
#include <linux/version.h>

#include "selinux_hide.h"
#include "policy/feature.h"
#include "manager/manager_identity.h"
#include "klog.h"
#include "selinux/selinux.h"

/*
 * Unified feature ID constants for cross-branch compatibility.
 *   dev branch:   uapi/feature.h has KSU_FEATURE_SELINUX_HIDE = 4,
 *                 KSU_FEATURE_SET_SELINUX_ENFORCE = 5 (in enum)
 *   legacy branch: uapi/feature.h has KSU_FEATURE_SELINUX_HIDE_STATUS = 4 (in enum),
 *                  no KSU_FEATURE_SET_SELINUX_ENFORCE
 * We use preprocessor defines (not enum) so they work with #ifndef and don't
 * conflict with either branch's enum definitions.
 */
#define KSU_FEATURE_ID_SELINUX_HIDE    4
#define KSU_FEATURE_ID_SELINUX_ENFORCE 5

/* ============= 类型定义 ============= */

typedef ssize_t (*write_op_fn)(struct file *file, char *buf, size_t size);
typedef int (*setprocattr_fn)(const char *name, void *value, size_t size);

/* ============= 只读内存写入支持 ============= */

/*
 * On arm64 with CONFIG_STRICT_KERNEL_RWX=y, write_op[] is 'static const'
 * and resides in .rodata. WRITE_ONCE on .rodata triggers a page fault.
 * We use set_memory_rw/ro (resolved via kallsyms) to temporarily mark
 * the target page writable, then restore read-only.
 */
typedef int (*set_mem_perm_fn)(unsigned long addr, int numpages);

static set_mem_perm_fn set_memory_rw_fn;
static set_mem_perm_fn set_memory_ro_fn;

static int init_ro_write(void)
{
	if (set_memory_rw_fn && set_memory_ro_fn)
		return 0;
	set_memory_rw_fn = (set_mem_perm_fn)kallsyms_lookup_name("set_memory_rw");
	set_memory_ro_fn = (set_mem_perm_fn)kallsyms_lookup_name("set_memory_ro");
	if (!set_memory_rw_fn || !set_memory_ro_fn) {
		pr_err("selinux_hide: set_memory_rw/ro not found in kallsyms\n");
		return -ENOENT;
	}
	return 0;
}

static void ro_write_slot(write_op_fn *slot, write_op_fn new_val)
{
	unsigned long page = (unsigned long)slot & PAGE_MASK;
	write_op_fn tmp = new_val;
	set_memory_rw_fn(page, 1);
	WRITE_ONCE(*slot, tmp);
	set_memory_ro_fn(page, 1);
}

/* ============= 常量 ============= */

#define KSU_DOMAIN_TAG   ":ksu:"
#define KSU_DOMAIN_TAG2  ":ksu_"
#define KSU_DOMAIN_FULL  "u:r:ksu:s0"

#ifndef SIMPLE_TRANSACTION_LIMIT
#define SIMPLE_TRANSACTION_LIMIT (PAGE_SIZE - sizeof(ssize_t))
#endif

/* ============= SELinux inode 编号 ============= */

enum sel_inos {
	SEL_ROOT_INO = 2,
	SEL_LOAD,
	SEL_ENFORCE,
	SEL_CONTEXT,
	SEL_ACCESS,
	SEL_CREATE,
	SEL_RELABEL,
	SEL_USER,
	SEL_POLICYVERS,
	SEL_COMMIT_BOOLS,
	SEL_MLS,
	SEL_DISABLE,
	SEL_MEMBER,
	SEL_CHECKREQPROT,
	SEL_COMPAT_NET,
	SEL_REJECT_UNKNOWN,
	SEL_DENY_UNKNOWN,
	SEL_STATUS,
	SEL_POLICY,
	SEL_VALIDATE_TRANS,
	SEL_INO_NEXT,
};

/* ============= 全局状态 ============= */

static DEFINE_MUTEX(selinux_hide_mutex);
static bool ksu_selinux_hide_enabled __read_mostly = false;
static bool ksu_selinux_hide_running __read_mostly = false;
static write_op_fn *selinux_write_op = NULL;
static write_op_fn *context_write_slot = NULL;
static write_op_fn *access_write_slot = NULL;
static write_op_fn orig_context_write = NULL;
static write_op_fn orig_access_write = NULL;
static setprocattr_fn orig_setprocattr = NULL;
static struct security_hook_list *setprocattr_entry = NULL;

/* ============= 辅助函数 ============= */

static bool buf_contains(const char *buf, size_t size, const char *needle)
{
	size_t needle_len;

	if (!buf || !needle || size == 0)
		return false;
	needle_len = strlen(needle);
	if (needle_len == 0 || needle_len > size)
		return false;
	return strnstr(buf, needle, size) != NULL;
}

static bool buf_mentions_ksu(const char *buf, size_t size)
{
	return buf_contains(buf, size, KSU_DOMAIN_TAG) ||
	       buf_contains(buf, size, KSU_DOMAIN_TAG2) ||
	       buf_contains(buf, size, KSU_DOMAIN_FULL);
}

/* ============= my_write_context (过滤模式) ============= */

static ssize_t my_write_context(struct file *file, char *buf, size_t size)
{
	if (likely(current_uid().val >= 10000 &&
		   ksu_selinux_hide_enabled &&
		   ksu_selinux_hide_running &&
		   current_uid().val != ksu_get_manager_appid())) {
		if (buf_mentions_ksu(buf, size))
			return -EINVAL;
	}
	return orig_context_write(file, buf, size);
}

/* ============= my_write_access (过滤模式) ============= */

static ssize_t my_write_access(struct file *file, char *buf, size_t size)
{
	if (likely(current_uid().val >= 10000 &&
		   ksu_selinux_hide_enabled &&
		   ksu_selinux_hide_running &&
		   current_uid().val != ksu_get_manager_appid())) {
		if (buf_mentions_ksu(buf, size)) {
			return scnprintf(buf, SIMPLE_TRANSACTION_LIMIT,
					 "%x %x %x %x %u %x",
					 0, 0xffffffff, 0, 0xffffffff, 0, 0);
		}
	}
	return orig_access_write(file, buf, size);
}

/* ============= my_setprocattr (直接操作 security_hook_heads) ============= */

static int my_setprocattr(const char *name, void *value, size_t size)
{
	if (ksu_selinux_hide_enabled &&
	    ksu_selinux_hide_running &&
	    current_uid().val >= 10000 &&
	    current_uid().val != ksu_get_manager_appid()) {
		if (name && !strcmp(name, "current")) {
			if (value && buf_mentions_ksu((const char *)value, size))
				return -EACCES;
		}
	}
	return orig_setprocattr(name, value, size);
}

/* ============= hook / unhook 安装 ============= */

static void hook_write_ops(void)
{
	if (selinux_write_op)
		return;

	if (init_ro_write()) {
		pr_err("selinux_hide: ro_write init failed, skipping write_op hook\n");
		return;
	}

	selinux_write_op = (write_op_fn *)kallsyms_lookup_name("write_op");
	if (!selinux_write_op) {
		pr_err("selinux_hide: write_op not found\n");
		return;
	}

	context_write_slot = &selinux_write_op[SEL_CONTEXT];
	orig_context_write = *context_write_slot;
	if (!orig_context_write) {
		pr_warn("selinux_hide: write_op[SEL_CONTEXT] is NULL, skipping\n");
		context_write_slot = NULL;
	} else {
		ro_write_slot(context_write_slot, my_write_context);
	}

	access_write_slot = &selinux_write_op[SEL_ACCESS];
	orig_access_write = *access_write_slot;
	if (!orig_access_write) {
		pr_warn("selinux_hide: write_op[SEL_ACCESS] is NULL, skipping\n");
		access_write_slot = NULL;
	} else {
		ro_write_slot(access_write_slot, my_write_access);
	}
}

static void hook_selinux_setprocattr(void)
{
	struct security_hook_heads *heads;
	setprocattr_fn target;

	if (setprocattr_entry)
		return;

	heads = (struct security_hook_heads *)kallsyms_lookup_name("security_hook_heads");
	if (!heads) {
		pr_err("selinux_hide: security_hook_heads not found\n");
		return;
	}

	target = (setprocattr_fn)kallsyms_lookup_name("selinux_setprocattr");
	if (!target) {
		pr_err("selinux_hide: selinux_setprocattr not found\n");
		return;
	}

	struct security_hook_list *hp;
	hlist_for_each_entry(hp, &heads->setprocattr, list) {
		if ((setprocattr_fn)hp->hook.setprocattr == target) {
			orig_setprocattr = target;
			setprocattr_entry = hp;
			WRITE_ONCE(hp->hook.setprocattr, my_setprocattr);
			pr_info("selinux_hide: selinux_setprocattr hooked\n");
			return;
		}
	}
	pr_err("selinux_hide: setprocattr entry not found in hook list\n");
}

static void unhook_write_ops(void)
{
	if (context_write_slot) {
		if (*context_write_slot == my_write_context)
			ro_write_slot(context_write_slot, orig_context_write);
		context_write_slot = NULL;
		orig_context_write = NULL;
	}
	if (access_write_slot) {
		if (*access_write_slot == my_write_access)
			ro_write_slot(access_write_slot, orig_access_write);
		access_write_slot = NULL;
		orig_access_write = NULL;
	}
}

static void unhook_selinux_setprocattr(void)
{
	if (!setprocattr_entry || !orig_setprocattr)
		return;

	WRITE_ONCE(setprocattr_entry->hook.setprocattr, (void *)orig_setprocattr);
	setprocattr_entry = NULL;
	orig_setprocattr = NULL;
}

/* ============= enable / disable / unhook ============= */

static int ksu_selinux_hide_enable(void)
{
	pr_info("selinux_hide: enabling\n");
	hook_write_ops();
	hook_selinux_setprocattr();
	return 0;
}

static void ksu_selinux_hide_unhook(void)
{
	pr_info("selinux_hide: unhooking\n");
	unhook_write_ops();
	unhook_selinux_setprocattr();
}

static void ksu_selinux_hide_disable(void)
{
	pr_info("selinux_hide: disabling\n");
	ksu_selinux_hide_unhook();
}

/* ============= Feature handler (get/set) ============= */

static int selinux_hide_feature_get(u64 *value)
{
	*value = ksu_selinux_hide_enabled ? 1 : 0;
	return 0;
}

static int selinux_hide_feature_set(u64 value)
{
	bool enable = value != 0;
	int ret = 0;

	pr_info("selinux_hide: set to %d\n", enable);

	mutex_lock(&selinux_hide_mutex);
	ksu_selinux_hide_enabled = enable;
	if (enable) {
		if (!ksu_selinux_hide_running) {
			ret = ksu_selinux_hide_enable();
			if (!ret)
				ksu_selinux_hide_running = true;
			else
				ksu_selinux_hide_enabled = false;
		}
	} else {
		if (ksu_selinux_hide_running) {
			ksu_selinux_hide_disable();
			ksu_selinux_hide_running = false;
		}
	}
	mutex_unlock(&selinux_hide_mutex);
	return ret;
}

static const struct ksu_feature_handler selinux_hide_handler = {
	.feature_id = KSU_FEATURE_ID_SELINUX_HIDE,
	.name = "selinux_hide",
	.get_handler = selinux_hide_feature_get,
	.set_handler = selinux_hide_feature_set,
};

/* ============= set_enforce feature handler ============= */

static int enforce_feature_get(u64 *value)
{
	*value = getenforce() ? 1 : 0;
	return 0;
}

static int enforce_feature_set(u64 value)
{
	bool enforce = value != 0;

	setenforce(enforce);
	if (getenforce() == enforce)
		return 0;

	return -EOPNOTSUPP;
}

static const struct ksu_feature_handler enforce_handler = {
	.feature_id = KSU_FEATURE_ID_SELINUX_ENFORCE,
	.name = "set_selinux_enforce",
	.get_handler = enforce_feature_get,
	.set_handler = enforce_feature_set,
};

/* ============= 公开 API ============= */

void __init ksu_selinux_hide_init(void)
{
	int ret;

	ret = ksu_register_feature_handler(&selinux_hide_handler);
	if (ret)
		pr_err("selinux_hide: failed to register feature handler: %d\n", ret);

	ret = ksu_register_feature_handler(&enforce_handler);
	if (ret)
		pr_err("selinux_hide: failed to register enforce handler: %d\n", ret);

	pr_info("selinux_hide: initialized (toggle to activate)\n");
}

void __exit ksu_selinux_hide_exit(void)
{
	mutex_lock(&selinux_hide_mutex);
	if (ksu_selinux_hide_running) {
		ksu_selinux_hide_disable();
		ksu_selinux_hide_running = false;
	}
	ksu_selinux_hide_enabled = false;
	mutex_unlock(&selinux_hide_mutex);

	ksu_unregister_feature_handler(KSU_FEATURE_ID_SELINUX_HIDE);
	ksu_unregister_feature_handler(KSU_FEATURE_ID_SELINUX_ENFORCE);
	pr_info("selinux_hide: exited\n");
}

void ksu_selinux_hide_drop_backup_if_unused(void)
{
	/* 过滤模式不依赖 backup_sepolicy, 无需操作 */
}

void ksu_selinux_hide_handle_second_stage(void)
{
	/* 过滤模式不需要第二阶段初始化 */
}

void ksu_selinux_hide_handle_post_fs_data(void)
{
	/* 过滤模式不需要 post-fs-data 初始化 */
}
