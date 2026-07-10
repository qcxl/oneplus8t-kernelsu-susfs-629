// SPDX-License-Identifier: GPL-2.0
/*
 * feature/selinux_hide.c — 统一版 SELinux hide (4.19)
 *
 * 合并版本 A (dev: ksu_patch_text + ksu_lsm_hook + fake_status) 和
 * 版本 B (注入: 过滤模式 + 直接 security_hook_heads 操作) 的最佳部分。
 *
 * 4.19 适配：
 *   - 过滤模式代替 backup_sepolicy (4.19 不支持 struct selinux_policy)
 *   - set_memory_rw/ro 直接改页表权限后 WRITE_ONCE 写 .rodata
 *     (ARM64 4.19 的 set_memory_rw 通过 apply_to_page_range(&init_mm, ...)
 *      修改任意内核虚拟地址的页表权限。CONFIG_STRICT_KERNEL_RWX 确保
 *      .rodata 为 4KB 页映射而非 section 映射，所以安全有效)
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

typedef ssize_t (*write_op_fn)(struct file *file, const char *buf, size_t size);
typedef int (*setprocattr_fn)(const char *name, void *value, size_t size);
typedef int (*set_mem_perm_fn)(unsigned long addr, int numpages);

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

static bool ksu_selinux_hide_enabled;
static bool ksu_selinux_hide_running;
static DEFINE_MUTEX(selinux_hide_mutex);

/* write_op 钩子 */
static write_op_fn *selinux_write_op;
static int write_op_inited;

static write_op_fn orig_context_write;
static write_op_fn *context_write_slot;
static write_op_fn orig_access_write;
static write_op_fn *access_write_slot;

/* setprocattr 钩子 */
static struct security_hook_list *setprocattr_entry;
static setprocattr_fn orig_setprocattr;

/* set_memory_rw/ro 函数指针 (通过 kallsyms 查找) */
static set_mem_perm_fn set_memory_rw_fn;
static set_mem_perm_fn set_memory_ro_fn;

/* ============= 工具函数 ============= */

/*
 * set_page_rw / set_page_ro
 * 通过内核导出的 set_memory_rw/set_memory_ro 修改 .rodata 页表权限。
 * ARM64 4.19 上 set_memory_rw 使用 apply_to_page_range(&init_mm, ...)
 * 遍历页表，适用于任意内核虚拟地址 (含 vmalloc 区)。
 */
static int init_set_mem_perm_fns(void)
{
	if (!set_memory_rw_fn) {
		set_memory_rw_fn = (set_mem_perm_fn)kallsyms_lookup_name("set_memory_rw");
		if (!set_memory_rw_fn) {
			pr_err("selinux_hide: set_memory_rw not found\n");
			return -ENOENT;
		}
	}
	if (!set_memory_ro_fn) {
		set_memory_ro_fn = (set_mem_perm_fn)kallsyms_lookup_name("set_memory_ro");
		if (!set_memory_ro_fn) {
			pr_err("selinux_hide: set_memory_ro not found\n");
			return -ENOENT;
		}
	}
	return 0;
}

static int set_page_rw(unsigned long addr)
{
	int ret;
	if (!set_memory_rw_fn)
		return -ENXIO;
	ret = set_memory_rw_fn(addr & PAGE_MASK, 1);
	if (ret)
		pr_err("selinux_hide: set_memory_rw(0x%lx) failed: %d\n", addr, ret);
	return ret;
}

static int set_page_ro(unsigned long addr)
{
	int ret;
	if (!set_memory_ro_fn)
		return -ENXIO;
	ret = set_memory_ro_fn(addr & PAGE_MASK, 1);
	if (ret)
		pr_err("selinux_hide: set_memory_ro(0x%lx) failed: %d\n", addr, ret);
	return ret;
}

/* ============= 过滤辅助函数 ============= */

static bool buf_mentions_ksu(const char *buf, size_t size)
{
	if (!buf)
		return false;
	if (strnstr(buf, KSU_DOMAIN_TAG, size))
		return true;
	if (strnstr(buf, KSU_DOMAIN_TAG2, size))
		return true;
	if (strnstr(buf, KSU_DOMAIN_FULL, size))
		return true;
	/* /sys/fs/selinux/context 内容格式: u:r:X:s0 */
	return false;
}

/* ============= my_write_context ============= */

static ssize_t my_write_context(struct file *file, const char *buf, size_t size)
{
	if (ksu_selinux_hide_enabled &&
	    ksu_selinux_hide_running &&
	    current_uid().val >= 10000 &&
	    current_uid().val != ksu_get_manager_appid()) {
		if (buf_mentions_ksu(buf, size)) {
			return size;
		}
	}
	if (unlikely(!orig_context_write))
		return -EIO;
	return orig_context_write(file, (char *)buf, size);
}

/* ============= my_write_access ============= */

static ssize_t my_write_access(struct file *file, const char *buf, size_t size)
{
	if (ksu_selinux_hide_enabled &&
	    ksu_selinux_hide_running &&
	    current_uid().val >= 10000 &&
	    current_uid().val != ksu_get_manager_appid()) {
		if (buf_mentions_ksu(buf, size)) {
			return scnprintf((char *)buf, SIMPLE_TRANSACTION_LIMIT,
					 "%x %x %x %x %u %x",
					 0, 0xffffffff, 0, 0xffffffff, 0, 0);
		}
	}
	if (unlikely(!orig_access_write))
		return -EIO;
	return orig_access_write(file, (char *)buf, size);
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
	if (unlikely(!orig_setprocattr))
		return -EIO;
	return orig_setprocattr(name, value, size);
}

/* ============= hook / unhook 安装 ============= */

static void hook_write_ops(void)
{
	write_op_fn *op;

	if (write_op_inited)
		return;

	pr_info("selinux_hide: hook_write_ops start\n");

	op = (write_op_fn *)kallsyms_lookup_name("write_op");
	if (!op) {
		pr_err("selinux_hide: write_op not found\n");
		return;
	}

	if (init_set_mem_perm_fns()) {
		pr_err("selinux_hide: set_memory_rw/ro not available\n");
		return;
	}

	selinux_write_op = op;
	write_op_inited = true;

	context_write_slot = &selinux_write_op[SEL_CONTEXT];
	orig_context_write = *context_write_slot;

	pr_info("selinux_hide: set_page_rw + WRITE_ONCE for context_write\n");
	if (set_page_rw((unsigned long)context_write_slot)) {
		pr_err("selinux_hide: cannot make context_write writable, bailing\n");
		context_write_slot = NULL;
		orig_context_write = NULL;
		goto skip_context;
	}
	WRITE_ONCE(*context_write_slot, my_write_context);
	set_page_ro((unsigned long)context_write_slot);
skip_context:

	access_write_slot = &selinux_write_op[SEL_ACCESS];
	orig_access_write = *access_write_slot;

	pr_info("selinux_hide: set_page_rw + WRITE_ONCE for access_write\n");
	if (set_page_rw((unsigned long)access_write_slot)) {
		pr_err("selinux_hide: cannot make access_write writable, bailing\n");
		access_write_slot = NULL;
		orig_access_write = NULL;
		goto skip_access;
	}
	WRITE_ONCE(*access_write_slot, my_write_access);
	set_page_ro((unsigned long)access_write_slot);
skip_access:

	if (!context_write_slot && !access_write_slot) {
		pr_err("selinux_hide: hook_write_ops: no write_op slots could be hooked\n");
		write_op_inited = false;
		return;
	}
	pr_info("selinux_hide: hook_write_ops done\n");
}

static void hook_selinux_setprocattr(void)
{
	struct security_hook_heads *heads;
	setprocattr_fn target;

	if (setprocattr_entry)
		return;

	pr_info("selinux_hide: hook_selinux_setprocattr start\n");

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
			pr_info("selinux_hide: replacing setprocattr with my_setprocattr\n");
			WRITE_ONCE(hp->hook.setprocattr, my_setprocattr);
			pr_info("selinux_hide: selinux_setprocattr hooked\n");
			return;
		}
	}
	pr_err("selinux_hide: setprocattr entry not found in hook list\n");
	pr_info("selinux_hide: hook_selinux_setprocattr done\n");
}

static void unhook_write_ops(void)
{
	if (context_write_slot) {
		if (*context_write_slot == my_write_context) {
			if (!set_page_rw((unsigned long)context_write_slot)) {
				WRITE_ONCE(*context_write_slot, orig_context_write);
				set_page_ro((unsigned long)context_write_slot);
			}
		}
		context_write_slot = NULL;
		orig_context_write = NULL;
	}

	if (access_write_slot) {
		if (*access_write_slot == my_write_access) {
			if (!set_page_rw((unsigned long)access_write_slot)) {
				WRITE_ONCE(*access_write_slot, orig_access_write);
				set_page_ro((unsigned long)access_write_slot);
			}
		}
		access_write_slot = NULL;
		orig_access_write = NULL;
	}

	write_op_inited = false;
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
	pr_info("selinux_hide: hook_write_ops returned, calling hook_selinux_setprocattr\n");
	hook_selinux_setprocattr();
	pr_info("selinux_hide: enable complete\n");
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

/* ============= KSU_FEATURE_SET_SELINUX_ENFORCE handler ============= */

static int enforce_feature_get(u64 *value)
{
	*value = getenforce() ? 1 : 0;
	return 0;
}

static int enforce_feature_set(u64 value)
{
	bool enforce = value != 0;
	setenforce(enforce);
	/* verify: if enforce didn't take effect, warn but don't fail */
	if (enforce != (bool)getenforce())
		pr_warn_ratelimited("selinux_hide: setenforce(%d) may not have taken effect (CONFIG_SECURITY_SELINUX_DEVELOP?)\n", enforce);
	return 0;
}

static const struct ksu_feature_handler enforce_handler = {
	.feature_id = KSU_FEATURE_ID_SELINUX_ENFORCE,
	.name = "selinux_enforce",
	.get_handler = enforce_feature_get,
	.set_handler = enforce_feature_set,
};

/* ============= 初始化 / 退出 ============= */

int __init ksu_selinux_hide_init(void)
{
	int ret;

	ret = ksu_register_feature_handler(&selinux_hide_handler);
	if (ret)
		pr_err("selinux_hide: failed to register feature handler: %d\n", ret);
	else
		pr_info("selinux_hide: initialized (toggle to activate)\n");

	ret = ksu_register_feature_handler(&enforce_handler);
	if (ret)
		pr_err("selinux_hide: failed to register enforce handler: %d\n", ret);

	return 0;
}

void __exit ksu_selinux_hide_exit(void)
{
	ksu_selinux_hide_unhook();
	ksu_unregister_feature_handler(KSU_FEATURE_ID_SELINUX_HIDE);
	ksu_unregister_feature_handler(KSU_FEATURE_ID_SELINUX_ENFORCE);
	pr_info("selinux_hide: exited\n");
}

module_init(ksu_selinux_hide_init);
module_exit(ksu_selinux_hide_exit);
