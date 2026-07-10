// SPDX-License-Identifier: GPL-2.0
/*
 * feature/selinux_hide.c — 统一版 SELinux hide (4.19)
 *
 * 合并版本 A (dev: ksu_patch_text + ksu_lsm_hook + fake_status) 和
 * 版本 B (注入: 过滤模式 + 直接 security_hook_heads 操作) 的最佳部分。
 *
 * 4.19 适配：
 *   - 过滤模式代替 backup_sepolicy (4.19 不支持 struct selinux_policy)
 *   - ksu_patch_text 在 4.19+KASLR 上不可靠，改用 fixmap ro_write：
 *     phys_from_virt(init_mm 页表遍历) → set_fixmap_offset(FIX_TEXT_POKE0)
 *     → memcpy → clear_fixmap。不依赖线性映射，不受 KASLR 影响。
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
#include <asm/fixmap.h>
#include <asm/pgtable.h>

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

/* ============= 工具函数 ============= */

/*
 * 通过 fixmap (FIX_TEXT_POKE0) 临时映射目标物理页为可写后写入，
 * 绕过 set_memory_rw 在 4.19+KASLR 上对 kernel image 地址返回 -22 的问题。
 *
 * 原理：
 *   1. phys_from_virt() 遍历 init_mm 页表，将目标虚拟地址转为物理地址
 *   2. set_fixmap_offset() 将物理页映射到 fixmap 虚拟地址空间 (可写映射)
 *   3. 写入目标数据到 fixmap 地址
 *   4. clear_fixmap() 释放临时映射
 *
 * 写入对象是 .rodata / .data..ro_after_init，非 .text 指令流，
 * 所以不需 stop_machine 也无需 dcache flush
 * (Cortex-A77 PIPT D-cache 写直达内存，原始映射即时可见)。
 */
static inline bool pmd_is_leaf(pmd_t pmd)
{
#if defined(pmd_leaf)
	return pmd_leaf(pmd);
#elif defined(pmd_sect)
	return pmd_sect(pmd);
#else
	return pmd_val(pmd) && !(pmd_val(pmd) & PMD_TABLE_BIT);
#endif
}

static inline bool pud_is_leaf(pud_t pud)
{
#if defined(pud_leaf)
	return pud_leaf(pud);
#elif defined(pud_sect)
	return pud_sect(pud);
#else
	return pud_val(pud) && !(pud_val(pud) & PUD_TABLE_BIT);
#endif
}

static unsigned long phys_from_virt(unsigned long addr)
{
	pgd_t *pgd;
	p4d_t *p4d;
	pud_t *pud;
	pmd_t *pmd;
	pte_t *pte;

	pgd = pgd_offset(&init_mm, addr);
	if (pgd_none(*pgd) || pgd_bad(*pgd))
		return 0;

	p4d = p4d_offset(pgd, addr);
	if (p4d_none(*p4d) || p4d_bad(*p4d))
		return 0;

	pud = pud_offset(p4d, addr);
	if (pud_is_leaf(*pud))
		return (pud_val(*pud) & PUD_MASK) + (addr & ~PUD_MASK);
	if (pud_none(*pud) || pud_bad(*pud))
		return 0;

	pmd = pmd_offset(pud, addr);
	if (pmd_is_leaf(*pmd))
		return (pmd_val(*pmd) & PMD_MASK) + (addr & ~PMD_MASK);
	if (pmd_none(*pmd) || pmd_bad(*pmd))
		return 0;

	pte = pte_offset_kernel(pmd, addr);
	if (pte_none(*pte))
		return 0;

	return (pte_val(*pte) & PHYS_MASK & PAGE_MASK) + (addr & ~PAGE_MASK);
}

static int ro_write(void *dst, const void *src, size_t size)
{
	unsigned long phys;
	void *mapped;

	phys = phys_from_virt((unsigned long)dst);
	if (!phys) {
		pr_err("selinux_hide: phys_from_virt(0x%lx) failed\n",
		       (unsigned long)dst);
		return -EFAULT;
	}

	mapped = set_fixmap_offset(FIX_TEXT_POKE0, phys);
	if (!mapped)
		return -ENOMEM;

	memcpy(mapped, src, size);
	clear_fixmap(FIX_TEXT_POKE0);
	return 0;
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
	write_op_fn tmp;

	if (write_op_inited)
		return;

	pr_info("selinux_hide: hook_write_ops start\n");

	op = (write_op_fn *)kallsyms_lookup_name("write_op");
	if (!op) {
		pr_err("selinux_hide: write_op not found\n");
		return;
	}

	selinux_write_op = op;

	context_write_slot = &selinux_write_op[SEL_CONTEXT];
	orig_context_write = *context_write_slot;

	pr_info("selinux_hide: ro_write (fixmap) for context_write\n");
	tmp = my_write_context;
	if (ro_write(context_write_slot, &tmp, sizeof(tmp))) {
		pr_err("selinux_hide: cannot write context_write, bailing\n");
		context_write_slot = NULL;
		orig_context_write = NULL;
		goto skip_context;
	}
skip_context:

	access_write_slot = &selinux_write_op[SEL_ACCESS];
	orig_access_write = *access_write_slot;

	pr_info("selinux_hide: ro_write (fixmap) for access_write\n");
	tmp = my_write_access;
	if (ro_write(access_write_slot, &tmp, sizeof(tmp))) {
		pr_err("selinux_hide: cannot write access_write, bailing\n");
		access_write_slot = NULL;
		orig_access_write = NULL;
		goto skip_access;
	}
skip_access:

	if (!context_write_slot && !access_write_slot) {
		pr_err("selinux_hide: hook_write_ops: no write_op slots could be hooked\n");
		return;
	}
	write_op_inited = true;
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
	setprocattr_fn tmp;
	hlist_for_each_entry(hp, &heads->setprocattr, list) {
		if ((setprocattr_fn)hp->hook.setprocattr == target) {
			orig_setprocattr = target;
			setprocattr_entry = hp;
			pr_info("selinux_hide: replacing setprocattr with my_setprocattr\n");
			tmp = my_setprocattr;
			if (ro_write(&hp->hook.setprocattr, &tmp,
				     sizeof(tmp))) {
				pr_err("selinux_hide: cannot write setprocattr\n");
				setprocattr_entry = NULL;
				orig_setprocattr = NULL;
				return;
			}
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
			ro_write(context_write_slot, &orig_context_write,
				 sizeof(orig_context_write));
		}
		context_write_slot = NULL;
		orig_context_write = NULL;
	}

	if (access_write_slot) {
		if (*access_write_slot == my_write_access) {
			ro_write(access_write_slot, &orig_access_write,
				 sizeof(orig_access_write));
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

	ro_write(&setprocattr_entry->hook.setprocattr, &orig_setprocattr,
		 sizeof(orig_setprocattr));
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

static bool ksu_selinux_hide_registered;

int __init ksu_selinux_hide_init(void)
{
	int ret;

	if (ksu_selinux_hide_registered) {
		pr_info("selinux_hide: already initialized, skipping\n");
		return 0;
	}

	ret = ksu_register_feature_handler(&selinux_hide_handler);
	if (ret) {
		pr_err("selinux_hide: failed to register feature handler: %d\n", ret);
		return ret;
	}
	pr_info("selinux_hide: initialized (toggle to activate)\n");

	ret = ksu_register_feature_handler(&enforce_handler);
	if (ret) {
		pr_err("selinux_hide: failed to register enforce handler: %d\n", ret);
		ksu_unregister_feature_handler(KSU_FEATURE_ID_SELINUX_HIDE);
		return ret;
	}

	ksu_selinux_hide_registered = true;
	return 0;
}

void __exit ksu_selinux_hide_exit(void)
{
	ksu_selinux_hide_registered = false;
	mutex_lock(&selinux_hide_mutex);
	ksu_selinux_hide_unhook();
	mutex_unlock(&selinux_hide_mutex);
	ksu_unregister_feature_handler(KSU_FEATURE_ID_SELINUX_HIDE);
	ksu_unregister_feature_handler(KSU_FEATURE_ID_SELINUX_ENFORCE);
	pr_info("selinux_hide: exited\n");
}

module_init(ksu_selinux_hide_init);
module_exit(ksu_selinux_hide_exit);
