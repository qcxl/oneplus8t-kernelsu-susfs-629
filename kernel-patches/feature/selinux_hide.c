// SPDX-License-Identifier: GPL-2.0
/*
 * feature/selinux_hide.c — 4.19 完整版 SELinux hide
 *
 * 移植自 KernelSU-Next dev 分支 kernel/feature/selinux_hide.c
 * 适配 kernel 4.19 (OnePlus 8T / kebab)
 *
 * 4 个隐藏钩子：
 *   1. fake status page   — 由 legacy 分支 commit 77b30272 提供（ksu_selinux_hide_status_*）
 *   2. context_write      — 本文件实现（过滤模式）
 *   3. access_write       — 本文件实现（过滤模式）
 *   4. setprocattr        — 本文件实现（直接修改 security_hook_heads 链表）
 *
 * 4.19 适配要点：
 *   - 用 kallsyms_lookup_name() 替代 find_kernel_symbol_exact()
 *   - 用 WRITE_ONCE() 直接指针赋值替代 ksu_patch_text()（4.19 无 CFI）
 *   - 用直接修改 security_hook_heads.setprocattr 链表替代 ksu_lsm_hook()
 *   - 不使用 backup_sepolicy（4.19 无 ksu_dup_sepolicy），改用过滤模式
 *
 * Feature ID: KSU_FEATURE_SELINUX_HIDE (=4，覆盖 legacy STATUS)
 *   - 注册时通过 ksu_register_feature_handler 的 overwrite 行为
 *     覆盖 legacy 的 SELINUX_HIDE_STATUS handler
 *   - 控制 context_write + access_write + setprocattr 三个钩子
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
#include "klog.h"
#include "selinux/selinux.h"

/* SIMPLE_TRANSACTION_LIMIT — 4.19 内核中可能在 proc_fs.h 已定义，
 * 这里做兜底定义，避免编译错误 */
#ifndef SIMPLE_TRANSACTION_LIMIT
#define SIMPLE_TRANSACTION_LIMIT (PAGE_SIZE - sizeof(ssize_t))
#endif

/* SELinux inode 编号（必须与 security/selinux/selinuxfs.c 中的 enum sel_inos 一致）
 * 来源：kernel 4.19 security/selinux/selinuxfs.c */
enum {
	SEL_ROOT_INO = 2,
	SEL_LOAD,          /* 3: load policy */
	SEL_ENFORCE,       /* 4: get/set enforcing */
	SEL_CONTEXT,       /* 5: validate context */
	SEL_ACCESS,        /* 6: compute access */
	SEL_CREATE,        /* 7: compute create labeling */
	SEL_RELABEL,       /* 8: compute relabeling */
	SEL_USER,          /* 9: compute reachable user contexts */
	SEL_POLICYVERS,    /* 10 */
	SEL_COMMIT_BOOLS,  /* 11 */
	SEL_MLS,           /* 12 */
	SEL_DISABLE,       /* 13 */
	SEL_MEMBER,        /* 14 */
	SEL_CHECKREQPROT,  /* 15 */
	SEL_COMPAT_NET,    /* 16 */
	SEL_REJECT_UNKNOWN,/* 17 */
	SEL_DENY_UNKNOWN,  /* 18 */
	SEL_STATUS,        /* 19: status via mmap */
	SEL_POLICY,        /* 20: in-kernel policy */
	SEL_VALIDATE_TRANS,/* 21 */
	SEL_INO_NEXT,      /* 22 */
};

/* KSU 域特征字符串 — 与 selinux/selinux.h 的 KERNEL_SU_DOMAIN 宏保持一致 */
#define KSU_DOMAIN_TAG	":ksu:"
#define KSU_DOMAIN_TAG2 ":ksu_"
#define KSU_DOMAIN_FULL "u:r:ksu:s0"

/* ============= 全局状态 ============= */

static DEFINE_MUTEX(selinux_hide_mutex);
static bool ksu_selinux_hide_enabled __read_mostly = false;
static bool ksu_selinux_hide_running __read_mostly = false;

/* ============= write_op[] hook ============= */

typedef ssize_t (*write_op_fn)(struct file *file, char *buf, size_t size);

static write_op_fn *selinux_write_op = NULL;
static write_op_fn *context_write_slot = NULL;
static write_op_fn *access_write_slot = NULL;
static write_op_fn orig_context_write = NULL;
static write_op_fn orig_access_write = NULL;

/* 在长度受限的缓冲区中查找子串（4.19 strnstr 签名） */
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

/* 检测 buffer 是否包含 KSU 域标记 */
static bool buf_mentions_ksu(const char *buf, size_t size)
{
	return buf_contains(buf, size, KSU_DOMAIN_TAG) ||
	       buf_contains(buf, size, KSU_DOMAIN_TAG2) ||
	       buf_contains(buf, size, KSU_DOMAIN_FULL);
}

/* ============= Route B1: my_write_context ============= */

static ssize_t my_write_context(struct file *file, char *buf, size_t size)
{
	/* 仅对 app uid 生效 */
	if (likely(current_uid().val >= 10000 &&
		   ksu_selinux_hide_enabled &&
		   ksu_selinux_hide_running)) {
		/* 过滤模式：app 验证 KSU 上下文时返回 -EINVAL，
		 * 让 app 认为 KSU 域不存在 */
		if (buf_mentions_ksu(buf, size)) {
			pr_info_ratelimited("ksu_selinux_hide: blocked context query for KSU domain\n");
			return -EINVAL;
		}
	}
	return orig_context_write(file, buf, size);
}

/* ============= Route B2: my_write_access ============= */

static ssize_t my_write_access(struct file *file, char *buf, size_t size)
{
	if (likely(current_uid().val >= 10000 &&
		   ksu_selinux_hide_enabled &&
		   ksu_selinux_hide_running)) {
		/* 过滤模式：app 计算 KSU 域相关访问决策时返回 deny-all
		 * 输出格式与 sel_write_access 一致：
		 * "allowed auditallow auditdeny seqno flags" */
		if (buf_mentions_ksu(buf, size)) {
			pr_info_ratelimited("ksu_selinux_hide: blocked access query for KSU domain\n");
			return scnprintf(buf, SIMPLE_TRANSACTION_LIMIT,
					 "%x %x %x %x %u %x",
					 0, 0xffffffff, 0, 0xffffffff, 0, 0);
		}
	}
	return orig_access_write(file, buf, size);
}

/* ============= Route A: my_setprocattr (LSM hook 链表替换) ============= */

typedef int (*setprocattr_fn)(const char *name, void *value, size_t size);
static setprocattr_fn orig_setprocattr = NULL;
static struct security_hook_list *setprocattr_entry = NULL;

/* 获取 selinux_state — 由 legacy 分支 selinux/selinux.c 提供 */
/* selinux_state 在 4.19 是全局变量，通过 #include <security.h> 可见 */

static int my_setprocattr(const char *name, void *value, size_t size)
{
	/* 仅对 app uid 生效 */
	if (ksu_selinux_hide_enabled &&
	    ksu_selinux_hide_running &&
	    current_uid().val >= 10000) {
		/* 仅拦截 "current" 属性切换 */
		if (name && !strcmp(name, "current")) {
			/* 检查目标上下文是否为 KSU 域 */
			if (value && buf_mentions_ksu((const char *)value, size)) {
				pr_info_ratelimited("ksu_selinux_hide: blocked setprocattr to KSU domain\n");
				return -EACCES;
			}
		}
	}
	return orig_setprocattr(name, value, size);
}

static void hook_selinux_setprocattr(void)
{
	struct security_hook_heads *heads;
	struct security_hook_list *hp;
	setprocattr_fn target;

	if (setprocattr_entry)
		return;

	heads = (struct security_hook_heads *)kallsyms_lookup_name("security_hook_heads");
	if (!heads) {
		pr_err("ksu_selinux_hide: security_hook_heads not found\n");
		return;
	}

	target = (setprocattr_fn)kallsyms_lookup_name("selinux_setprocattr");
	if (!target) {
		pr_err("ksu_selinux_hide: selinux_setprocattr not found\n");
		return;
	}

	hlist_for_each_entry(hp, &heads->setprocattr, list) {
		if ((setprocattr_fn)hp->hook.setprocattr == target) {
			orig_setprocattr = target;
			setprocattr_entry = hp;
			/* 直接替换函数指针 — 4.19 无 CFI，安全 */
			WRITE_ONCE(hp->hook.setprocattr, (void *)my_setprocattr);
			pr_info("ksu_selinux_hide: selinux_setprocattr hooked\n");
			return;
		}
	}
	pr_err("ksu_selinux_hide: setprocattr entry not found in hook list\n");
}

static void unhook_selinux_setprocattr(void)
{
	if (!setprocattr_entry || !orig_setprocattr)
		return;

	WRITE_ONCE(setprocattr_entry->hook.setprocattr, (void *)orig_setprocattr);
	setprocattr_entry = NULL;
	orig_setprocattr = NULL;
	pr_info("ksu_selinux_hide: selinux_setprocattr unhooked\n");
}

/* ============= write_op[] hook 安装/卸载 ============= */

static void hook_write_ops(void)
{
	if (selinux_write_op)
		return;

	selinux_write_op = (write_op_fn *)kallsyms_lookup_name("write_op");
	if (!selinux_write_op) {
		pr_err("ksu_selinux_hide: write_op symbol not found, context/access hooks disabled\n");
		return;
	}

	/* Hook SEL_CONTEXT (index 5) */
	context_write_slot = &selinux_write_op[SEL_CONTEXT];
	orig_context_write = *context_write_slot;
	if (!orig_context_write) {
		pr_warn("ksu_selinux_hide: write_op[SEL_CONTEXT] is NULL, skipping\n");
		context_write_slot = NULL;
	} else {
		/* 4.19 无 CFI，直接指针赋值即可。WRITE_ONCE 保证原子性，
		 * smp_wmb() 保证其他 CPU 先看到指针再看到新函数 */
		smp_wmb();
		WRITE_ONCE(*context_write_slot, my_write_context);
		pr_info("ksu_selinux_hide: hooked write_op[SEL_CONTEXT]\n");
	}

	/* Hook SEL_ACCESS (index 6) */
	access_write_slot = &selinux_write_op[SEL_ACCESS];
	orig_access_write = *access_write_slot;
	if (!orig_access_write) {
		pr_warn("ksu_selinux_hide: write_op[SEL_ACCESS] is NULL, skipping\n");
		access_write_slot = NULL;
	} else {
		smp_wmb();
		WRITE_ONCE(*access_write_slot, my_write_access);
		pr_info("ksu_selinux_hide: hooked write_op[SEL_ACCESS]\n");
	}
}

static void unhook_write_ops(void)
{
	/* 恢复时先写回原指针，再 smp_wmb */
	if (context_write_slot && orig_context_write) {
		WRITE_ONCE(*context_write_slot, orig_context_write);
		smp_wmb();
		context_write_slot = NULL;
		orig_context_write = NULL;
		pr_info("ksu_selinux_hide: unhooked write_op[SEL_CONTEXT]\n");
	}
	if (access_write_slot && orig_access_write) {
		WRITE_ONCE(*access_write_slot, orig_access_write);
		smp_wmb();
		access_write_slot = NULL;
		orig_access_write = NULL;
		pr_info("ksu_selinux_hide: unhooked write_op[SEL_ACCESS]\n");
	}
	selinux_write_op = NULL;
}

/* ============= enable/disable ============= */

static int ksu_selinux_hide_enable(void)
{
	pr_info("ksu_selinux_hide: enabling\n");
	hook_write_ops();
	hook_selinux_setprocattr();
	/* Also set SELinux to permissive so all operations work */
	setenforce(false);
	return 0;
}

static void ksu_selinux_hide_disable(void)
{
	pr_info("ksu_selinux_hide: disabling\n");
	/* Only unhook write_ops (stop faking SELinux context queries).
	 * Keep setprocattr hook active: KSU domain processes need it.
	 * 
	 * IMPORTANT: Never call setenforce(true) here. Restoring enforcing
	 * after running permissive crashes the system - SELinux starts denying
	 * previously-allowed operations, killing critical services.
	 * User must reboot to restore enforcing mode. */
	unhook_write_ops();
}

/* ============= Feature handler ============= */

static int selinux_hide_feature_get(u64 *value)
{
	*value = ksu_selinux_hide_enabled ? 1 : 0;
	return 0;
}

static int selinux_hide_feature_set(u64 value)
{
	bool enable = !!value;
	int ret = 0;

	pr_info("ksu_selinux_hide: set to %d\n", enable);

	mutex_lock(&selinux_hide_mutex);
	if (enable == ksu_selinux_hide_enabled) {
		pr_info("ksu_selinux_hide: no change needed\n");
		goto out;
	}

	ksu_selinux_hide_enabled = enable;
	if (enable) {
		if (!ksu_selinux_hide_running) {
			ret = ksu_selinux_hide_enable();
			if (!ret)
				ksu_selinux_hide_running = true;
			else
				ksu_selinux_hide_enabled = false;  /* 回滚 */
		}
	} else {
		if (ksu_selinux_hide_running) {
			ksu_selinux_hide_disable();
			ksu_selinux_hide_running = false;
		}
	}
out:
	mutex_unlock(&selinux_hide_mutex);
	return ret;
}

static const struct ksu_feature_handler selinux_hide_handler = {
	.feature_id = KSU_FEATURE_SELINUX_HIDE,
	.name = "selinux_hide",
	.get_handler = selinux_hide_feature_get,
	.set_handler = selinux_hide_feature_set,
};

/* ============= 公开 API（init.c 调用） ============= */

void ksu_selinux_hide_handle_second_stage(void)
{
	/* second_stage 主要给 fake status page 用（legacy 已实现）。
	 * 本文件无需特殊处理，仅打 log。 */
	pr_info("ksu_selinux_hide: second_stage (no-op for hooks)\n");
}

void ksu_selinux_hide_handle_post_fs_data(void)
{
	/* post_fs_data 主要给 fake status page 用（legacy 已实现）。
	 * 本文件无需特殊处理，仅打 log。 */
	pr_info("ksu_selinux_hide: post_fs_data (no-op for hooks)\n");
}

void __init ksu_selinux_hide_init(void)
{
	int ret;

	ret = ksu_register_feature_handler(&selinux_hide_handler);
	if (ret) {
		pr_err("ksu_selinux_hide: failed to register feature handler: %d\n", ret);
		return;
	}

	/* 默认自动开启 — 与 dev 分支行为一致（dev 的 selinux_hide 默认 false，
	 * 由 ksud 设置；这里默认 true 以匹配用户现有 inject-selinux-hide.py 行为）。
	 *
	 * 注意：如果 ksud 不识别此 feature ID，会保持默认值。
	 * 用户可通过 ksud 命令手动关闭：
	 *   ksud feature set selinux_hide 0
	 */
	mutex_lock(&selinux_hide_mutex);
	ksu_selinux_hide_enabled = true;
	if (!ksu_selinux_hide_running) {
		ret = ksu_selinux_hide_enable();
		if (!ret)
			ksu_selinux_hide_running = true;
		else
			ksu_selinux_hide_enabled = false;
	}
	mutex_unlock(&selinux_hide_mutex);

	pr_info("ksu_selinux_hide: initialized (enabled=%d, running=%d)\n",
		ksu_selinux_hide_enabled, ksu_selinux_hide_running);
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

	ksu_unregister_feature_handler(KSU_FEATURE_SELINUX_HIDE);
	pr_info("ksu_selinux_hide: exited\n");
}
