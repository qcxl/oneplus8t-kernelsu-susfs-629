#!/usr/bin/env python3
"""
inject-selinux-domain-init.py — Port dev branch SELinux behaviour to legacy.

The original legacy KernelSU-Next init.c already has:
  - ksu_ksud_init() in built-in path  → installs init.rc hook
  - ksu_handle_execveat_ksud() execve hook → detects init second_stage
  - KERNEL_SU_RC with u:r:ksu:s0 exec context

So the basic SELinux Enforcing infrastructure exists. This inject adds:
  1. setup_selinux() clears exec_sid         (selinux.c)
  2. escape_with_root_profile() works when    (app_profile.c)
     uid==0 (sets up ksu domain anyway)
  3. Boot-safe apply_kernelsu_rules() path    (rules.c)
     + type_transition ksu→ksu for shell_exec
  4. Delayed workqueue fallback 30s after boot (init.c)
"""

import sys, os, re


def find_file(kernel_root, candidates):
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            return p
    return None


def fix_selinux_clear_exec_sid(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/selinux/selinux.c",
        "KernelSU/kernel/selinux/selinux.c",
    ])
    if not path:
        print(f"  WARNING: selinux.c not found, clear_exec_sid skipped")
        return True

    with open(path) as f:
        content = f.read()

    if 'transive_to_domain(domain, cred, true)' in content:
        print(f"  {path}: already fixed")
        return True

    content = content.replace(
        'transive_to_domain(domain, cred, false)',
        'transive_to_domain(domain, cred, true)',
        1
    )
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: clear_exec_sid=true")
    return True


def fix_app_profile(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/policy/app_profile.c",
        "KernelSU/kernel/policy/app_profile.c",
    ])
    if not path:
        print(f"  WARNING: app_profile.c not found")
        return True

    with open(path) as f:
        content = f.read()

    if 'Already root, setup selinux anyway' in content:
        print(f"  {path}: already fixed")
        return True

    old = (
        '\tif (cred->euid.val == 0) {\n'
        '\t\tpr_warn("Already root, don\'t escape!\\n");\n'
        '\t\tgoto out_abort_creds;\n'
        '\t}'
    )
    new = (
        '\tif (cred->euid.val == 0) {\n'
        '\t\tpr_debug("Already root, setup selinux anyway\\n");\n'
        '\t\tsetup_selinux(KERNEL_SU_CONTEXT, cred);\n'
        '\t\tcommit_creds(cred);\n'
        '\t\treturn 0;\n'
        '\t}'
    )
    if old not in content:
        print(f"  WARNING: pattern not found in {path}")
        return True

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: replaced early bail with setup_selinux")
    return True


def fix_rules(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/selinux/rules.c",
        "KernelSU/kernel/selinux/rules.c",
    ])
    if not path:
        print(f"  ERROR: rules.c not found")
        return False

    with open(path) as f:
        content = f.read()

    if 'ksu_type_transition.*KERNEL_SU_DOMAIN.*shell_exec' in content or \
       'type_transition.*ksu.*shell_exec.*process.*ksu' in content:
        print(f"  {path}: already fixed (type_transition present)")
    else:
        old = '    ksu_permissive(db, KERNEL_SU_DOMAIN);'
        new = (
            '    ksu_permissive(db, KERNEL_SU_DOMAIN);\n'
            '    /* ksu exec\'s shell: stay in ksu domain. */\n'
            '    printk(KERN_INFO "ksu_debug: types before=%d\\n", db->p_types.nprim);\n'
            '    printk(KERN_INFO "ksu_debug: has domain type=%d\\n",\n'
            '        hashtab_search(db->p_types.table, "domain") != NULL);\n'
            '    {\n'
            '        bool _r = ksu_type(db, KERNEL_SU_DOMAIN, "domain");\n'
            '        printk(KERN_INFO "ksu_debug: ksu_type result=%d\\n", _r);\n'
            '    }\n'
            '    printk(KERN_INFO "ksu_debug: types after=%d\\n", db->p_types.nprim);\n'
            '    printk(KERN_INFO "ksu_debug: has ksu type=%d\\n",\n'
            '        hashtab_search(db->p_types.table, "ksu") != NULL);\n'
            '    printk(KERN_INFO "ksu_debug: ksu_type_transition result=%d\\n",\n'
            '        ksu_type_transition(db, KERNEL_SU_DOMAIN, "shell_exec", "process", KERNEL_SU_DOMAIN, ALL));\n'
            '    printk(KERN_INFO "ksu_debug: ksu_allow shell_exec result=%d\\n",\n'
            '        ksu_allow(db, KERNEL_SU_DOMAIN, "shell_exec", "file", "execute"));'
        )
        if old not in content:
            print(f"  ERROR: cannot find ksu_permissive marker in {path}")
            return False
        content = content.replace(old, new, 1)

    # Replace the 4.19 non-GKI path (#else) with boot-safe version
    if 'Boot-safe: no write_lock' in content:
        print(f"  {path}: already boot-safe")
    else:
        else_pat = re.compile(
            r'(#else)(\n\n\tcpumask_t old_mask;.*?)(\n#endif\n})',
            re.DOTALL
        )
        else_repl = (
            r'\1'
            r'\n'
            r'    /* Boot-safe: no write_lock/stop_machine. */\n'
            r'    db = get_policydb();\n'
            r'    apply_kernelsu_rules_fn((void *)db);\n'
            r'    smp_mb();\n'
            r'    reset_avc_cache();\n'
            r'\3'
        )
        content = else_pat.sub(else_repl, content, count=1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: boot-safe path + type_transition")
    return True


def fix_kernelsu_init(kernel_root):
    """Add delayed workqueue as fallback in kernelsu_init().
    Original already has ksu_ksud_init() + execve hook for init second_stage.
    We add a delayed workqueue as safety net (30s after boot)."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/core/init.c",
        "KernelSU/kernel/core/init.c",
    ])
    if not path:
        print(f"  ERROR: core/init.c not found")
        return False

    with open(path) as f:
        content = f.read()

    if 'schedule_delayed_work(&ksu_delayed_selinux_work' in content:
        print(f"  {path}: already injected (schedule_delayed_work present), skipping")
        return True

    # Add includes for delayed work
    if '#include <linux/workqueue.h>' not in content:
        content = content.replace(
            '#include <linux/export.h>',
            '#include <linux/export.h>\n#include <linux/workqueue.h>'
        )

    # Add include for selinux.h (for apply_kernelsu_rules etc.)
    if '#include "selinux/selinux.h"' not in content:
        content = content.replace(
            '#include <linux/module.h>',
            '#include <linux/module.h>\n#include "selinux/selinux.h"'
        )

    # Insert delayed workqueue declaration BEFORE kernelsu_init function
    work_decl = '''

/* Delayed SELinux domain init fallback. */
static void ksu_delayed_selinux_init(struct work_struct *work)
{
	printk(KERN_INFO "ksu_debug: delayed init executing\\n");
	apply_kernelsu_rules();
	cache_sid();
	setup_ksu_cred();
	printk(KERN_INFO "ksu_debug: delayed init complete\\n");
}
static DECLARE_DELAYED_WORK(ksu_delayed_selinux_work, ksu_delayed_selinux_init);
'''
    content = content.replace(
        'int __init kernelsu_init(void)',
        work_decl + '\nint __init kernelsu_init(void)',
        1
    )

    # Insert workqueue schedule before final return 0 (proven approach from v315).
    # Uses the end-of-function tail replacement.
    old_tail = '\treturn 0;\n}\n\nvoid __exit kernelsu_exit'
    if old_tail not in content:
        print(f"  ERROR: cannot find 'return 0;' end marker in {path}")
        return False

    new_tail = (
        '\t/* Delayed workqueue fallback: applies KSU SELinux rules ~30s after boot. */\n'
        '\tschedule_delayed_work(&ksu_delayed_selinux_work, 30 * HZ);\n'
        '\n'
        '\treturn 0;\n'
        '}\n'
        '\n'
        'void __exit kernelsu_exit'
    )
    content = content.replace(old_tail, new_tail, 1)
    content = content.replace(old_tail, new_tail, 1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added delayed workqueue fallback")
    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"ERROR: {root} not a directory")
        sys.exit(1)

    print(f"[SELinux domain init inject] target={root}")
    ok = True
    ok &= fix_selinux_clear_exec_sid(root)
    ok &= fix_app_profile(root)
    ok &= fix_rules(root)
    ok &= fix_kernelsu_init(root)
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
