#!/usr/bin/env python3
"""
inject-susfs-dispatch.py - Inject SUSFS Kconfig menu + dispatch glue
into KernelSU-Next legacy tree.

Usage: python3 inject-susfs-dispatch.py <kernel-root>

This script:
1. Appends SUSFS Kconfig menu to KernelSU/kernel/Kconfig
2. Adds include + dispatch code to KernelSU/kernel/core/main.c
3. Adds susfs_init() call to KernelSU/kernel/core/init.c
"""

import sys
import os
import re

def path_exists(probe_dir, *paths):
    for p in paths:
        if os.path.exists(os.path.join(probe_dir, p)):
            return p
    return None


def patch_kconfig(kernel_root):
    """Append SUSFS Kconfig menu if not already present"""
    kconfig_path = path_exists(kernel_root,
        "KernelSU/kernel/Kconfig",
        "drivers/kernelsu/Kconfig")
    if not kconfig_path:
        print("ERROR: cannot find KernelSU Kconfig")
        return False
    kconfig_path = os.path.join(kernel_root, kconfig_path)

    with open(kconfig_path) as f:
        content = f.read()
    if "config KSU_SUSFS" in content:
        print("  Kconfig: SUSFS menu already present, skipping")
        return True

    menu = '''
menu "KernelSU - SUSFS"
config KSU_SUSFS
    bool "KernelSU addon - SUSFS"
    depends on KSU
    default y
    help
      Patch and Enable SUSFS to kernel with KernelSU.

config KSU_SUSFS_HAS_MAGIC_MOUNT
    bool "Say yes if the current KernelSU repo has magic mount implemented (default n)"
    depends on KSU
    default n
    help
      Enable to indicate that the current SUSFS kernel supports magic mount.

config KSU_SUSFS_SUS_PATH
    bool "Enable to hide suspicious path"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_SUS_MOUNT
    bool "Enable to hide suspicious mounts"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
    bool "Enable to hide KSU default mounts automatically"
    depends on KSU_SUSFS_SUS_MOUNT
    default y

config KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
    bool "Enable to hide suspicious bind mounts automatically"
    depends on KSU_SUSFS_SUS_MOUNT
    default y

config KSU_SUSFS_SUS_KSTAT
    bool "Enable to spoof suspicious kstat"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_SUS_OVERLAYFS
    bool "Enable to automatically spoof kstat for overlayed files"
    depends on KSU_SUSFS
    default n

config KSU_SUSFS_TRY_UMOUNT
    bool "Enable to use ksu_try_umount"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT
    bool "Enable to add bind mounts to try_umount automatically"
    depends on KSU_SUSFS_TRY_UMOUNT
    default y

config KSU_SUSFS_SPOOF_UNAME
    bool "Enable to spoof uname"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_ENABLE_LOG
    bool "Enable logging susfs log to kernel"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
    bool "Enable to automatically hide ksu and susfs symbols from /proc/kallsyms"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
    bool "Enable to spoof /proc/bootconfig (gki) or /proc/cmdline (non-gki)"
    depends on KSU_SUSFS
    default y

config KSU_SUSFS_OPEN_REDIRECT
    bool "Enable to redirect a path to be opened with another path"
    depends on KSU_SUSFS
    default y

endmenu
'''
    with open(kconfig_path, 'a') as f:
        f.write(menu)
    print(f"  Kconfig: SUSFS menu appended to {kconfig_path}")
    return True


def patch_core_init(kernel_root):
    """Add susfs_init() call to init function"""
    candidates = [
        "KernelSU/kernel/core/init.c",
        "KernelSU/kernel/ksu.c",
    ]
    init_path = None
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            init_path = p
            break
    if not init_path:
        print("WARNING: cannot find kernel init file for susfs_init()")
        return False

    with open(init_path) as f:
        content = f.read()
    if "susfs_init" in content:
        print(f"  Init: susfs_init() already present in {init_path}")
        return True

    # Find the line with module_init or the end of the init function
    # Look for a pr_alert/printk that says something about KernelSU banner,
    # then insert susfs_init() after it
    lines = content.split('\n')
    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if not inserted and 'KernelSU' in line and ('pr_alert' in line or 'pr_info' in line or 'printk' in line):
            # Insert susfs_init after the banner
            indent = ' ' * (len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}/* SUSFS init */')
            new_lines.append(f'{indent}#ifdef CONFIG_KSU_SUSFS')
            new_lines.append(f'{indent}    susfs_init();')
            new_lines.append(f'{indent}#endif')
            inserted = True

    with open(init_path, 'w') as f:
        f.write('\n'.join(new_lines))
    print(f"  Init: susfs_init() added to {init_path}")
    return True


def patch_core_main(kernel_root):
    """Add SUSFS dispatch code to the prctl handler"""
    candidates = [
        "KernelSU/kernel/core/main.c",
        "KernelSU/kernel/core_hook.c",
    ]
    main_path = None
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            main_path = p
            break
    if not main_path:
        print("ERROR: cannot find core/main.c for dispatch")
        return False

    with open(main_path) as f:
        content = f.read()
    if "CMD_SUSFS_ADD_SUS_PATH" in content:
        print(f"  Dispatch: SUSFS dispatch already present in {main_path}")
        return True

    # 1. Add include for susfs.h
    if '#include <linux/susfs.h>' not in content:
        content = content.replace(
            '#include "core_hook.h"',
            '#include "core_hook.h"\n#include <linux/susfs.h>')
        content = content.replace(
            '#include "../core_hook.h"',
            '#include "../core_hook.h"\n#include <linux/susfs.h>')

    # 2. Add SUSFS dispatch block before "all other cmds" fallback
    #    Look for something like "all other cmds" or the fallback comment
    dispatch_block = """
#ifdef CONFIG_KSU_SUSFS
\tif (current_uid().val == 0) {
\t\tvoid __user *uarg = (void __user *)arg3;
\t\tswitch (arg2) {
\t\tcase CMD_SUSFS_ADD_SUS_PATH:
\t\t\tsusfs_add_sus_path((struct st_susfs_sus_path __user *)uarg);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_ADD_SUS_MOUNT:
\t\t\tsusfs_add_sus_mount((struct st_susfs_sus_mount __user *)uarg);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_ADD_SUS_KSTAT:
\t\t\tsusfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_UPDATE_SUS_KSTAT:
\t\t\tsusfs_update_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_SET_UNAME:
\t\t\tsusfs_set_uname((struct st_susfs_uname __user *)uarg);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_ADD_OPEN_REDIRECT:
\t\t\tsusfs_add_open_redirect((struct st_susfs_open_redirect __user *)uarg);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_ENABLE_LOG:
\t\t\tsusfs_set_log((bool)arg3);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG:
\t\t\tsusfs_set_cmdline_or_bootconfig((char __user *)uarg);
\t\t\treturn 0;
\t\tcase CMD_SUSFS_SHOW_VERSION:
\t\t\tif (copy_to_user(uarg, SUSFS_VERSION, strlen(SUSFS_VERSION)+1))
\t\t\t\tpr_err("susfs: copy_to_user failed\\n");
\t\t\treturn 0;
\t\tcase CMD_SUSFS_SHOW_ENABLED_FEATURES: {
\t\t\tu64 enabled = 0;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\t\t\tenabled |= (1 << 0);
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
\t\t\tenabled |= (1 << 1);
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
\t\t\tenabled |= (1 << 4);
#endif
#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
\t\t\tenabled |= (1 << 6);
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
\t\t\tenabled |= (1 << 8);
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
\t\t\tenabled |= (1 << 9);
#endif
#ifdef CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
\t\t\tenabled |= (1 << 10);
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
\t\t\tenabled |= (1 << 11);
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\t\t\tenabled |= (1 << 12);
#endif
\t\t\tif (copy_to_user(uarg, &enabled, sizeof(u64)))
\t\t\t\tpr_err("susfs: copy_to_user failed\\n");
\t\t\treturn 0;
\t\t}
\t\tdefault:
\t\t\tbreak;
\t\t}
\t}
#endif
"""

    # Try to find the right insertion point
    # Look for patterns like "all other cmds" or the end of prctl
    patterns = [
        (r'// all other cmds', 'Insert before "all other cmds"'),
        (r'/\*.*all other cmds.*\*/', 'Insert before "all other cmds" comment'),
    ]
    inserted = False
    for pat, desc in patterns:
        match = re.search(pat, content)
        if match:
            pos = match.start()
            before = content[:pos]
            after = content[pos:]
            content = before + dispatch_block + after
            inserted = True
            print(f"  Dispatch: added before \"{desc}\"")
            break

    if not inserted:
        # Fallback: Find the return -EINVAL at end of a block and insert before
        # Look for the last "return 0" or "default:" in the prctl handler
        # Simple approach: insert at end of file before module_init
        print("  WARNING: could not auto-place dispatch, appending to file")
        content += f"\n{dispatch_block}\n"

    with open(main_path, 'w') as f:
        f.write(content)
    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <kernel-root>")
        sys.exit(1)

    kernel_root = sys.argv[1]
    if not os.path.isdir(kernel_root):
        print(f"ERROR: {kernel_root} is not a directory")
        sys.exit(1)

    print("[SUSFS inject]")
    print(f"  Target: {kernel_root}")
    ok = True
    ok &= patch_kconfig(kernel_root)
    ok &= patch_core_init(kernel_root)
    ok &= patch_core_main(kernel_root)
    print(f"  Result: {'OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
