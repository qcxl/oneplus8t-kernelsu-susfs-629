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


def fix_ksud_integration(kernel_root):
    """Remove u:r:ksu:s0 from post-fs-data exec in KERNEL_SU_RC."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/ksud_integration.c",
        "KernelSU/kernel/runtime/ksud_integration.c",
    ])
    if not path:
        print(f"  ERROR: ksud_integration.c not found")
        return False

    with open(path) as f:
        content = f.read()

    pattern = re.compile(
        r'^([ \t]*)"([ \t]*)exec u:r:"\s*KERNEL_SU_DOMAIN\s*":s0 root -- "\s*KSUD_PATH\s*" post-fs-data\\n"',
        re.MULTILINE
    )
    replacement = r'\1"\2exec root -- " KSUD_PATH " post-fs-data\\n"'
    new_content, count = pattern.subn(replacement, content, count=1)

    if count == 0:
        if re.search(r'exec root --.*KSUD_PATH.*post-fs-data', content):
            print(f"  Already fixed, skipping")
            return True
        print(f"  ERROR: cannot find post-fs-data exec pattern in {path}")
        return False

    with open(path, 'w') as f:
        f.write(new_content)
    print(f"  {path}: post-fs-data exec context removed")
    return True


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
        f'{indent}/* Initialize KSU SELinux domain */\n'
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
        '    /* Without this, stock type_transition domain->shell fires, losing perms. */\n'
        '    ksu_type_transition(db, KERNEL_SU_DOMAIN, "shell_exec", "process", KERNEL_SU_DOMAIN, ALL);\n'
        '    ksu_allow(db, KERNEL_SU_DOMAIN, "shell_exec", "file", "execute");'
    )

    if old not in content:
        print(f"  ERROR: cannot find ksu_permissive marker in {path}")
        return False

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added type_transition ksu→shell_exec→ksu")
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

    # Add #include "selinux/selinux.h" if not present
    if '#include "selinux/selinux.h"' not in content:
        content = content.replace(
            '#include "klog.h"',
            '#include "klog.h"\n#include "selinux/selinux.h"'
        )

    # Find the final return 0; in kernelsu_init() and insert before it.
    # kernelsu_init() ends with:
    #   #endif
    #     return 0;
    #   }
    # ...
    # void __exit kernelsu_exit
    marker = re.compile(
        r'(\treturn 0;\n}\n\nvoid __exit kernelsu_exit)',
        re.MULTILINE
    )
    if not marker.search(content):
        print(f"  ERROR: cannot find kernelsu_init() end marker in {path}")
        return False

    calls = (
        '\t/* Initialize KSU SELinux domain (SELinux is fully initialized at this point) */\n'
        '\tapply_kernelsu_rules();\n'
        '\tcache_sid();\n'
        '\tsetup_ksu_cred();\n'
        '\n'
        '\treturn 0;\n'
        '}\n'
        '\n'
        'void __exit kernelsu_exit'
    )
    content = marker.sub(calls, content, count=1)

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
    ok &= fix_ksud_integration(root)
    ok &= fix_boot_event(root)
    ok &= fix_selinux_clear_exec_sid(root)
    ok &= fix_rules(root)
    ok &= fix_kernelsu_init(root)
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
