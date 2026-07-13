#!/usr/bin/env python3
"""
inject-selinux-domain-init.py - Fix SELinux ksu domain init for builtin mode.

On builtin mode (non-LKM), the init second_stage execve hook doesn't fire on
some kernels (e.g. LineageOS 4.19), so apply_kernelsu_rules() is never called.
This means u:r:ksu:s0 never gets created in the SELinux policy, and all file
operations fail under Enforcing mode.

Fix:
  1. Remove u:r:ksu:s0 requirement from post-fs-data exec in KERNEL_SU_RC
     (chicken-and-egg: the context doesn't exist yet when init runs this exec)
  2. Add apply_kernelsu_rules() + cache_sid() + setup_ksu_cred() to
     on_post_fs_data() in boot_event.c so they run reliably at boot.

Files modified:
  drivers/kernelsu/runtime/ksud_integration.c
  drivers/kernelsu/runtime/boot_event.c

Returns 0 on success, 1 on failure.
"""

import sys, os


def find_file(kernel_root, candidates):
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            return p
    return None

def fix_ksud_integration(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/ksud_integration.c",
        "KernelSU/kernel/runtime/ksud_integration.c",
    ])
    if not path:
        print(f"  ERROR: ksud_integration.c not found")
        return False

    with open(path) as f:
        content = f.read()

    old = '    "    exec u:r:" KERNEL_SU_DOMAIN ":s0 root -- " KSUD_PATH " post-fs-data\\n"'
    new = '    "    exec root -- " KSUD_PATH " post-fs-data\\n"'

    if old not in content:
        print(f"  WARNING: pattern not found in {path}, checking if already fixed...")
        if new in content:
            print(f"  Already fixed, skipping")
            return True
        print(f"  ERROR: cannot find pattern to fix")
        return False

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: post-fs-data exec context removed")
    return True


def fix_boot_event(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/boot_event.c",
        "KernelSU/kernel/runtime/boot_event.c",
    ])
    if not path:
        print(f"  ERROR: boot_event.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # 1. Add include
    include_line = '#include "selinux/selinux.h"'
    if include_line not in content:
        # Insert after the first include line
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
        else:
            content = include_line + '\n' + content
            print(f"  {path}: added #include selinux/selinux.h (no prior include)")
    else:
        print(f"  {path}: include already present")

    # 2. Add calls before ksu_load_allow_list
    marker = '\tksu_load_allow_list();'
    block = (
        '\t/* Initialize KSU SELinux domain */\n'
        '\tapply_kernelsu_rules();\n'
        '\tcache_sid();\n'
        '\tsetup_ksu_cred();\n'
        '\n'
        '\tksu_load_allow_list();'
    )

    if marker not in content:
        print(f"  ERROR: cannot find ksu_load_allow_list() marker in {path}")
        return False

    # Check if already applied
    if 'apply_kernelsu_rules()' in content:
        print(f"  Already applied, skipping")
        return True

    content = content.replace(marker, block, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added apply_kernelsu_rules + cache_sid + setup_ksu_cred")
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
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
