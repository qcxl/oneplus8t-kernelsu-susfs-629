#!/usr/bin/env python3
"""
inject-selinux-hide.py — Route A only: setprocattr hook
4.19 限制：policydb_* 是 SELinux SS 内部函数，KSU 模块无权访问。
因此 Route B (context/access + vfs write_op backup) 不可行。

仅注入到 selinux.c + feature.h。无需 sepolicy.c/rules.c/selinux.h 变更。
"""

import sys, os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_SELINUX_HIDE_INJECTED */"

def resolve(path):
    for base in [KSU, KERNEL_ROOT]:
        p = os.path.join(base, path)
        if os.path.exists(p):
            return p
    return os.path.join(KSU, path)

def inject(filepath, anchor, snippet, after=True):
    fp = resolve(filepath)
    if not os.path.exists(fp): print(f"  ERROR: {fp} not found"); return False
    with open(fp) as f: c = f.read()
    if SCRIPT_MARK in c: print(f"  SKIP: {fp} already injected"); return True
    if anchor not in c: print(f"  ERROR: anchor not found in {fp}"); return False
    block = "\n" + SCRIPT_MARK + "\n" + snippet.strip() + "\n"
    c = c.replace(anchor, (anchor + block) if after else (block + anchor), 1)
    with open(fp, 'w') as f: f.write(c)
    print(f"  OK: {fp}")
    return True

SELINUX_HIDE_CORE = """
#include <linux/rwlock.h>
#include <linux/lsm_hooks.h>
#include "policy/feature.h"
#include <linux/init.h>

static bool ksu_selinux_hide_enabled __read_mostly = false;
static DEFINE_MUTEX(ksu_selinux_hide_mutex);

typedef int (*setprocattr_fn)(const char *, void *, size_t);
static setprocattr_fn orig_setprocattr;
static struct security_hook_list *setprocattr_entry;

static int my_setprocattr(const char *name, void *value, size_t size)
{
	if (ksu_selinux_hide_enabled && current_uid().val >= 10000) {
		int error; u32 mysid = current_sid(), sid; char *str = value;
		error = avc_has_perm(&selinux_state, mysid, mysid, SECCLASS_PROCESS, PROCESS__SETCURRENT, NULL);
		if (error) return error;
		if (size && str[0] && str[0] != '\\n') {
			if (str[size - 1] == '\\n') { str[size - 1] = 0; size--; }
			error = security_context_to_sid(&selinux_state, str, size, &sid, GFP_KERNEL);
			if (error) return error;
		}
	}
	return orig_setprocattr(name, value, size);
}

static void hook_selinux_setprocattr(void)
{
	struct security_hook_heads *heads; struct security_hook_list *hp; setprocattr_fn target;
	if (setprocattr_entry) return;
	heads = (struct security_hook_heads *)kallsyms_lookup_name("security_hook_heads");
	target = (setprocattr_fn)kallsyms_lookup_name("selinux_setprocattr");
	if (!heads || !target) { pr_err("ksu_selinux_hide: symbols not found\\n"); return; }
	hlist_for_each_entry(hp, &heads->setprocattr, list) {
		if ((setprocattr_fn)hp->hook.setprocattr == target) {
			orig_setprocattr = target; setprocattr_entry = hp;
			hp->hook.setprocattr = (void *)my_setprocattr;
			pr_info("ksu_selinux_hide: selinux_setprocattr hooked\\n"); return;
		}
	}
	pr_err("ksu_selinux_hide: setprocattr entry not found\\n");
}

static void unhook_selinux_setprocattr(void)
{
	if (setprocattr_entry && orig_setprocattr) {
		setprocattr_entry->hook.setprocattr = (void *)orig_setprocattr;
		setprocattr_entry = NULL; orig_setprocattr = NULL;
	}
}

static int selinux_hide_enable(void)
{
	pr_info("ksu_selinux_hide: enable\\n");
	hook_selinux_setprocattr();
	return 0;
}

static void selinux_hide_disable(void)
{
	pr_info("ksu_selinux_hide: disable\\n");
	unhook_selinux_setprocattr();
}

static int selinux_hide_get(u64 *value) { *value = ksu_selinux_hide_enabled ? 1 : 0; return 0; }
static int selinux_hide_set(u64 value)
{
	bool enable = !!value; int ret = 0;
	mutex_lock(&ksu_selinux_hide_mutex);
	ksu_selinux_hide_enabled = enable;
	if (enable) ret = selinux_hide_enable();
	else selinux_hide_disable();
	mutex_unlock(&ksu_selinux_hide_mutex);
	return ret;
}

static const struct ksu_feature_handler selinux_hide_handler = {
	.feature_id = KSU_FEATURE_SELINUX_HIDE, .name = "selinux_hide",
	.get_handler = selinux_hide_get, .set_handler = selinux_hide_set,
};

static int __init ksu_selinux_hide_init(void)
{
	return ksu_register_feature_handler(&selinux_hide_handler);
}
postcore_initcall(ksu_selinux_hide_init);
"""

UAPI_FEATURE_ENUM = "\tKSU_FEATURE_SELINUX_HIDE = 5, /* selinux_hide route A: setprocattr */"

FILES = {
    "selinux.c": "selinux/selinux.c",
    "feature.h": "include/uapi/feature.h",
}

def main():
    print("[selinux_hide] target=%s" % KERNEL_ROOT)
    ok = True

    # 1. selinux.c: insert core code (Route A: setprocattr only)
    ok &= inject(FILES["selinux.c"], "void ksu_selinux_hide_status_handle_second_stage(void)", SELINUX_HIDE_CORE, after=False)

    # 2. uapi/feature.h: add KSU_FEATURE_SELINUX_HIDE
    ok &= inject(FILES["feature.h"], "KSU_FEATURE_SELINUX_HIDE_STATUS = 4,", UAPI_FEATURE_ENUM)

    print("  Result: %s" % ("ALL OK" if ok else "SOME FAILURES"))
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
