#!/usr/bin/env python3
"""Inject susfs_task_state clearing into anon_ksu_ioctl in supercall.c.
Called from CI after inject-ksu-prctl.py.

The upstream KernelSU-Next@legacy branch uses 4-space indentation.
The pattern to match is:
    return ksu_supercall_handle_ioctl(cmd, (void __user *)arg);

Usage: python3 inject-susfs-taskstate.py <kernel-root>
"""

import sys, os

def main():
    if len(sys.argv) < 2:
        print("Usage: inject-susfs-taskstate.py <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    path = os.path.join(root, "drivers/kernelsu/supercall/supercall.c")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found")
        sys.exit(1)

    with open(path) as f:
        content = f.read()

    if 'susfs_task_state = 0' in content:
        print("  already has susfs_task_state clear, skipping")
        return

    # Upstream uses 4-space indentation (NOT tabs)
    old = '    return ksu_supercall_handle_ioctl(cmd, (void __user *)arg);'
    new = (
        '    /* SUSFS: exempt KSU processes from path hiding. */\n'
        '    /* Bit(24) is set from fork; clear it so KSU callers see hidden paths. */\n'
        '#ifdef CONFIG_KSU_SUSFS\n'
        '    current->susfs_task_state = 0;\n'
        '#endif\n'
        '    return ksu_supercall_handle_ioctl(cmd, (void __user *)arg);'
    )

    if old not in content:
        print(f"  WARNING: pattern not found in {path}")
        print(f"  Looked for: {repr(old)}")
        sys.exit(0)

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: susfs_task_state clear injected")

if __name__ == '__main__':
    main()
