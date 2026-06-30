#!/usr/bin/env python3
"""
inject-susfs-dispatch.py - Inject SUSFS dispatch into KernelSU-Next legacy.

KSUN legacy uses ioctl dispatch table (supercall/dispatch.c), NOT prctl.
This script adds SUSFS handlers to the ioctl table and initializes SUSFS.

Files modified:
  drivers/kernelsu/core/init.c       - add #include + susfs_init()
  drivers/kernelsu/supercall/dispatch.c - add SUSFS ioctl handler + table entry

Returns 0 on success, 1 on failure.
"""

import sys, os, re


def add_include_after_last(content, header):
    """Insert '#include <header>' after the last #include line."""
    lines = content.split('\n')
    last = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('#include'):
            last = i
    if last >= 0:
        lines.insert(last + 1, f'#include <{header}>')
        return '\n'.join(lines), True
    lines.insert(0, f'#include <{header}>')
    return '\n'.join(lines), True


def add_susfs_handlers_to_dispatch(kernel_root):
    """Add SUSFS ioctl handler + table entry to supercall/dispatch.c"""
    candidates = [
        "drivers/kernelsu/supercall/dispatch.c",
        "KernelSU/kernel/supercall/dispatch.c",
    ]
    dp_path = None
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            dp_path = p
            break
    if not dp_path:
        print("  ERROR: supercall/dispatch.c not found")
        return False

    with open(dp_path) as f:
        content = f.read()
    if "KSU_IOCTL_SUSFS" in content:
        print(f"  Dispatch: SUSFS already present in {dp_path}")
        return True

    # 1. Add includes
    for hdr in ['linux/susfs.h', 'linux/susfs_def.h']:
        if hdr not in content:
            content, ok = add_include_after_last(content, hdr)
            if not ok:
                print(f"  ERROR: could not add include <{hdr}>")
                return False

    # 2. Add SUSFS handler function. Insert BEFORE ksu_ioctl_handlers[] array.
    handler_code = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS\n'
        '/* SUSFS ioctl handler - routes sub-commands to susfs.c functions */\n'
        'struct ksu_susfs_ioctl {\n'
        '\t__u32 cmd_id;\n'
        '\t__u64 arg_ptr;\n'
        '};\n'
        '\n'
        'static int do_susfs_ioctl(void __user *arg)\n'
        '{\n'
        '\tstruct ksu_susfs_ioctl ioctl;\n'
        '\tvoid __user *uarg;\n'
        '\n'
        '\tif (copy_from_user(&ioctl, arg, sizeof(ioctl)))\n'
        '\t\treturn -EFAULT;\n'
        '\tpr_info("susfs: ioctl cmd=0x%x\\n", ioctl.cmd_id);\n'
        '\tif (current_uid().val != 0)\n'
        '\t\treturn -EPERM;\n'
        '\tuarg = (void __user *)(uintptr_t)ioctl.arg_ptr;\n'
        '\tswitch (ioctl.cmd_id) {\n'
        '\tcase CMD_SUSFS_ADD_SUS_PATH:\n'
        '\t\treturn susfs_add_sus_path((struct st_susfs_sus_path __user *)uarg);\n'
        '\tcase CMD_SUSFS_ADD_SUS_MOUNT:\n'
        '\t\treturn susfs_add_sus_mount((struct st_susfs_sus_mount __user *)uarg);\n'
        '\tcase CMD_SUSFS_ADD_SUS_KSTAT:\n'
        '\t\treturn susfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);\n'
        '\tcase CMD_SUSFS_UPDATE_SUS_KSTAT:\n'
        '\t\treturn susfs_update_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);\n'
        '\tcase CMD_SUSFS_SET_UNAME:\n'
        '\t\treturn susfs_set_uname((struct st_susfs_uname __user *)uarg);\n'
        '\tcase CMD_SUSFS_ADD_OPEN_REDIRECT:\n'
        '\t\treturn susfs_add_open_redirect((struct st_susfs_open_redirect __user *)uarg);\n'
        '\tcase CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG:\n'
        '\t\treturn susfs_set_cmdline_or_bootconfig((char __user *)uarg);\n'
        '\tcase CMD_SUSFS_ENABLE_LOG:\n'
        '\t\tsusfs_set_log((bool)ioctl.arg_ptr);\n'
        '\t\treturn 0;\n'
        '\tcase CMD_SUSFS_SHOW_VERSION:\n'
        '\t\tif (copy_to_user(uarg, SUSFS_VERSION, strlen(SUSFS_VERSION)+1))\n'
        '\t\t\tpr_err("susfs: copy_to_user failed\\n");\n'
        '\t\treturn 0;\n'
        '\tdefault:\n'
        '\t\treturn -EINVAL;\n'
        '\t}\n'
        '}\n'
        '#endif /* CONFIG_KSU_SUSFS */\n'
        '\n'
    )

    # Insert before 'static const struct ksu_ioctl_cmd_map ksu_ioctl_handlers[]'
    marker = 'static const struct ksu_ioctl_cmd_map ksu_ioctl_handlers'
    pos = content.find(marker)
    if pos < 0:
        print("  ERROR: cannot find ksu_ioctl_handlers table in dispatch.c")
        return False
    content = content[:pos] + handler_code + content[pos:]

    # 3. Add table entry after the marker (which moved due to insertion)
    #    Recalculate position after insertion
    pos = content.find(marker)
    # Find the last entry before the sentinel (0, NULL, NULL, NULL)
    sentinel = '{0,.name=NULL,.handler=NULL,.perm_check=NULL}'
    s_pos = content.find(sentinel, pos)
    if s_pos < 0:
        # Try alternative sentinel format
        sentinel = '{\n        .cmd = 0,'
        s_pos = content.find(sentinel, pos)
    if s_pos < 0:
        print("  ERROR: cannot find sentinel entry in dispatch table")
        return False
    
    table_entry = (
        '    {\n'
        '        .cmd = KSU_IOCTL_SUSFS,\n'
        '        .name = "SUSFS",\n'
        '#ifdef CONFIG_KSU_SUSFS\n'
        '        .handler = do_susfs_ioctl,\n'
        '#else\n'
        '        .handler = NULL,\n'
        '#endif\n'
        '        .perm_check = only_root\n'
        '    },\n'
    )
    content = content[:s_pos] + table_entry + content[s_pos:]

    with open(dp_path, 'w') as f:
        f.write(content)
    print(f"  Dispatch: SUSFS ioctl handler added to {dp_path}")
    return True


def add_susfs_ioctl_define(kernel_root):
    """Add KSU_IOCTL_SUSFS command definition to KSUN uapi header."""
    candidates = [
        "drivers/kernelsu/include/uapi/supercall.h",
        "KernelSU/kernel/include/uapi/supercall.h",
    ]
    uapi_path = None
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            uapi_path = p
            break
    if not uapi_path:
        print("  WARNING: uapi/supercall.h not found (creating it)")
        # Find the include/uapi directory
        for base in ["drivers/kernelsu/include/uapi", "KernelSU/kernel/include/uapi"]:
            d = os.path.join(kernel_root, base)
            if os.path.isdir(d):
                uapi_path = os.path.join(d, "supercall.h")
                break
        if not uapi_path:
            print("  WARNING: cannot find uapi directory for supercall.h")
            return True  # Non-fatal - the define can go elsewhere

    content = ''
    if os.path.exists(uapi_path):
        with open(uapi_path) as f:
            content = f.read()

    if 'KSU_IOCTL_SUSFS' in content:
        print(f"  UAPI: KSU_IOCTL_SUSFS already defined")
        return True

    define = (
        '\n'
        '#define KSU_IOCTL_SUSFS 0x55\n'
    )
    with open(uapi_path, 'a') if os.path.exists(uapi_path) else open(uapi_path, 'w') as f:
        f.write(define)
    print(f"  UAPI: KSU_IOCTL_SUSFS added to {uapi_path}")
    return True


def patch_core_init(kernel_root):
    """Add include + susfs_init() call to init file."""
    candidates = [
        "drivers/kernelsu/core/init.c",
        "drivers/kernelsu/ksu.c",
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
        print("  ERROR: no init file found (checked: {})".format(
            ', '.join(candidates)))
        return False

    with open(init_path) as f:
        content = f.read()
    if "susfs_init" in content:
        print(f"  Init: susfs_init() already present in {init_path}")
        return True

    if '<linux/susfs.h>' not in content:
        content, ok = add_include_after_last(content, 'linux/susfs.h')
        if not ok:
            print("  ERROR: could not add include to init file")
            return False

    # Insert susfs_init() call: find banner line or module_init
    lines = content.split('\n')
    new_lines = []
    inserted = False
    banner_pats = [
        re.compile(r'(pr_alert|pr_info|printk)\s*\(.*KernelSU'),
    ]
    for line in lines:
        new_lines.append(line)
        if not inserted and any(p.search(line) for p in banner_pats):
            indent = ' ' * max(4, len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}#ifdef CONFIG_KSU_SUSFS')
            new_lines.append(f'{indent}    susfs_init();')
            new_lines.append(f'{indent}#endif')
            inserted = True

    if not inserted:
        for i, line in enumerate(lines):
            m = re.match(r'module_init\s*\(\s*(\w+)\s*\)\s*;', line.strip())
            if m:
                fn_name = m.group(1)
                for j in range(i - 1, -1, -1):
                    if re.search(r'\b' + re.escape(fn_name) + r'\s*\(', lines[j]):
                        fn_text = '\n'.join(lines[j:])
                        depth = 0
                        started = False
                        close = -1
                        for k, ch in enumerate(fn_text):
                            if ch == '{':
                                depth += 1
                                started = True
                            elif ch == '}':
                                depth -= 1
                                if started and depth == 0:
                                    close = j + fn_text[:k].count('\n')
                                    break
                        if close > 0:
                            lines.insert(close, '\n\t/* susfs init */\n\t#ifdef CONFIG_KSU_SUSFS\n\t    susfs_init();\n\t#endif\n')
                            inserted = True
                            new_lines = lines
                        break
                break

    content = '\n'.join(new_lines)
    if not inserted:
        print("  ERROR: could not find insertion point for susfs_init()")
        return False

    with open(init_path, 'w') as f:
        f.write(content)
    print(f"  Init: susfs_init() added to {init_path}")
    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"ERROR: {root} not a directory")
        sys.exit(1)

    print(f"[SUSFS inject] target={root}")
    ok = True
    ok &= patch_core_init(root)
    ok &= add_susfs_handlers_to_dispatch(root)
    ok &= add_susfs_ioctl_define(root)
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
