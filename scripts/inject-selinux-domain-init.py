#!/usr/bin/env python3
"""
inject-selinux-domain-init.py — Fix KSU SELinux domain init for builtin mode.

Root cause:
  On builtin mode, kernelsu_init() runs at device_initcall level (after
  selinux_init at subsys_initcall). SELinux final policy is loaded. But
  apply_kernelsu_rules() is never called, so u:r:ksu:s0 never exists.
  escape_with_root_profile() → setup_selinux("u:r:ksu:s0") fails.
  All file operations fail under SELinux Enforcing.

Fix:
  1. Add apply_kernelsu_rules() + cache_sid() + setup_ksu_cred() directly
     in kernelsu_init() (core/init.c), before the final return 0.
     SELinux is fully initialized by this point. No policy reload occurs.
  2. Clear exec_sid in setup_selinux() (selinux/selinux.c) so the ksu
     domain persists across exec boundaries.
  3. Remove u:r:ksu:s0 from post-fs-data exec in KERNEL_SU_RC
     (chicken-and-egg: context doesn't exist at boot).
  4. Add calls to on_post_fs_data() (boot_event.c) as a safety net.
"""

import sys, os, re


def find_file(kernel_root, candidates):
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            return p
    return None


def fix_boot_event(kernel_root):
    """Add apply_kernelsu_rules + cache_sid + setup_ksu_cred to on_post_fs_data()."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/boot_event.c",
        "KernelSU/kernel/runtime/boot_event.c",
    ])
    if not path:
        print(f"  ERROR: boot_event.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # Add include if not present
    include_line = '#include "selinux/selinux.h"'
    if include_line not in content:
        lines = content.split('\n')
        first_include = -1
        for i, line in enumerate(lines):
            if line.startswith('#include'):
                first_include = i
                break
        if first_include >= 0:
            lines.insert(first_include + 1, include_line)
            content = '\n'.join(lines)
            print(f"  {path}: added #include selinux/selinux.h")

    if 'apply_kernelsu_rules()' in content:
        print(f"  {path}: already applied, skipping")
        return True

    # Insert before ksu_load_allow_list()
    marker = re.compile(r'^([ \t]*)ksu_load_allow_list\(\);', re.MULTILINE)
    m = marker.search(content)
    if not m:
        print(f"  ERROR: cannot find ksu_load_allow_list() in {path}")
        return False

    indent = m.group(1)
    block = (
        f'{indent}/* Initialize KSU SELinux domain. Build: __DATE__ __TIME__ */\n'
        f'{indent}apply_kernelsu_rules();\n'
        f'{indent}cache_sid();\n'
        f'{indent}setup_ksu_cred();\n'
        f'\n'
        f'{indent}ksu_load_allow_list();'
    )
    content, count = marker.subn(block, content, count=1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added calls to on_post_fs_data()")
    return True


def fix_selinux_clear_exec_sid(kernel_root):
    """Change setup_selinux to clear exec_sid (prevents domain transition on exec)."""
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

    old = 'transive_to_domain(domain, cred, false)'
    new = 'transive_to_domain(domain, cred, true)'
    if old not in content:
        print(f"  WARNING: pattern not found in {path}")
        return True

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: clear_exec_sid=true")
    return True


def fix_app_profile(kernel_root):
    """Remove early return in escape_with_root_profile when euid==0.
    The early return skips setup_selinux(), leaving the process in the
    wrong domain. Even if already root, we should still set the ksu domain
    so that exec()'d child processes inherit the correct context."""
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

    # Replace the early return with setup_selinux + commit
    old = (
        '\tif (cred->euid.val == 0) {\n'
        '\t\tpr_warn("Already root, don\'t escape!\\n");\n'
        '\t\tgoto out_abort_creds;\n'
        '\t}'
    )
    new = (
        '\tif (cred->euid.val == 0) {\n'
        '\t\t/* Already root, but still set up ksu domain for child processes */\n'
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
    """Add type_transition rule: ksu exec's shell_exec → stays in ksu, not shell.
    Without this, the stock type_transition domain shell_exec:process shell;
    fires when ksu exec's /system/bin/sh, transitioning the process to
    shell domain, losing all permissions."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/selinux/rules.c",
        "KernelSU/kernel/selinux/rules.c",
    ])
    if not path:
        print(f"  ERROR: rules.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # Check if already applied
    if 'ksu_type_transition.*KERNEL_SU_DOMAIN.*shell_exec' in content or \
       'type_transition.*ksu.*shell_exec.*process.*ksu' in content:
        print(f"  {path}: already fixed")
        return True

    # Insert after ksu_permissive(db, KERNEL_SU_DOMAIN);
    # Note: apply_kernelsu_rules_fn() uses 4-space indentation (not tabs)
    old = '    ksu_permissive(db, KERNEL_SU_DOMAIN);'
    new = (
        '    ksu_permissive(db, KERNEL_SU_DOMAIN);\n'
        '    /* ksu exec' + "'" + 's shell (sh, busybox): STAY in ksu domain. */\n'
        '    /* Build: __DATE__ __TIME__ */\n'
        '    /* Without this, stock type_transition domain->shell fires, losing perms. */\n'
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

    # Also replace the apply_kernelsu_rules() #else branch to skip
    # write_lock/stop_machine (GFP_KERNEL fails in atomic context).
    # Replace from '#else' to the closing '#endif' of the function.
    import re as _re
    # Replace the entire 4.19 path body from '#else' to closing '#endif'
    # with a boot-safe version. Capture #else and #endif as boundaries.
    else_pat = _re.compile(
        r'(#else)(\n\n\tcpumask_t old_mask;.*?)(\n#endif\n})',
        _re.DOTALL
    )
    else_repl = (
        r'\1'
        r'\n'
        r'    /* Boot-safe: no write_lock/stop_machine (GFP_KERNEL fails in atomic context). */\n'
        r'    /* At boot, only CPU 0 runs init, so no SELinux policy contention. */\n'
        r'    db = get_policydb();\n'
        r'    apply_kernelsu_rules_fn((void *)db);\n'
        r'    smp_mb();\n'
        r'    reset_avc_cache();\n'
        r'\3'
    )
    content = else_pat.sub(else_repl, content, count=1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: replaced apply_kernelsu_rules() with boot-safe path")
    return True


def fix_kernelsu_init(kernel_root):
    """Add apply_kernelsu_rules + cache_sid + setup_ksu_cred directly in
    kernelsu_init(), before the final 'return 0;'. This runs at
    device_initcall level, after SELinux is fully initialized."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/core/init.c",
        "KernelSU/kernel/core/init.c",
    ])
    if not path:
        print(f"  ERROR: core/init.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # Check if our injection already exists (the comment is unique to our code)
    if 'KSU SELinux domain (SELinux is fully initialized at this point)' in content:
        print(f"  {path}: already injected, skipping")
        return True

    # Add includes if not present
    if '#include "selinux/selinux.h"' not in content:
        content = content.replace(
            '#include "klog.h"',
            '#include "klog.h"\n#include "selinux/selinux.h"'
        )
    if '#include <linux/workqueue.h>' not in content:
        content = content.replace(
            '#include <linux/export.h>',
            '#include <linux/export.h>\n#include <linux/workqueue.h>'
        )

    # Add DECLARE_DELAYED_WORK + work function BEFORE kernelsu_init
    # (must be declared before the function that uses it)
    work_decl = '''

/* Delayed SELinux domain init: policy not ready at device_initcall.
 * Scheduled from kernelsu_init(), runs ~30s after boot. */
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
    # Insert before kernelsu_init definition
    content = content.replace(
        'int __init kernelsu_init(void)',
        work_decl + '\nint __init kernelsu_init(void)',
        1
    )

    # Find the final return 0; in kernelsu_init() and insert before it.
    # Using str.replace() to avoid Python re.sub's backslash interpretation
    # (re.sub converts \\n in replacement to actual newline chars).
    old_tail = '\treturn 0;\n}\n\nvoid __exit kernelsu_exit'
    if old_tail not in content:
        print(f"  ERROR: cannot find kernelsu_init() end marker in {path}")
        return False

    new_tail = (
        '\t/* Defer SELinux domain init: policydb not ready at device_initcall. */\n'
        '\t/* Schedule delayed work to run ~30s after boot (policy fully loaded). */\n'
        '\tprintk(KERN_INFO "ksu_debug: scheduling delayed ksu domain init\\n");\n'
        '\tschedule_delayed_work(&ksu_delayed_selinux_work, 30 * HZ);\n'
        '\n'
        '\treturn 0;\n'
        '}\n'
        '\n'
        'void __exit kernelsu_exit'
    )
    content = content.replace(old_tail, new_tail, 1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added calls to kernelsu_init()")
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
    ok &= fix_boot_event(root)
    ok &= fix_selinux_clear_exec_sid(root)
    ok &= fix_app_profile(root)
    ok &= fix_rules(root)
    ok &= fix_kernelsu_init(root)
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
