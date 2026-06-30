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
        '/* SUSFS ioctl command */\n'
        '#ifndef KSU_IOCTL_SUSFS\n'
        '#define KSU_IOCTL_SUSFS 0x55\n'
        '#endif\n'
        '\n'
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
        '\tcase CMD_SUSFS_SHOW_VARIANT:\n'
        '\t\tif (copy_to_user(uarg, SUSFS_VARIANT, strlen(SUSFS_VARIANT)+1))\n'
        '\t\t\tpr_err("susfs: copy_to_user failed\\n");\n'
        '\t\treturn 0;\n'
        '\tcase CMD_SUSFS_SHOW_ENABLED_FEATURES: {\n'
        '\t\tu64 enabled = 0;\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n'
        '\t\tenabled |= (1 << 0);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n'
        '\t\tenabled |= (1 << 1);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n'
        '\t\tenabled |= (1 << 4);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT\n'
        '\t\tenabled |= (1 << 6);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME\n'
        '\t\tenabled |= (1 << 8);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG\n'
        '\t\tenabled |= (1 << 9);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS\n'
        '\t\tenabled |= (1 << 10);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG\n'
        '\t\tenabled |= (1 << 11);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n'
        '\t\tenabled |= (1 << 12);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
        '\t\tenabled |= (1 << 13);\n'
        '#endif\n'
        '\t\tif (copy_to_user(uarg, &enabled, sizeof(u64)))\n'
        '\t\t\tpr_err("susfs: copy_to_user failed\\n");\n'
        '\t\treturn 0;\n'
        '\t}\n'
        '\tcase CMD_SUSFS_ADD_SUS_MAP:\n'
        '\t\tsusfs_add_sus_map(&uarg);\n'
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
    # Find the sentinel entry (cmd = 0, handler = NULL)
    # Match each field explicitly with flexible whitespace
    sentinel_pat = re.compile(
        r'\.cmd\s*=\s*0\s*,\s*'
        r'\.name\s*=\s*NULL\s*,\s*'
        r'\.handler\s*=\s*NULL\s*,\s*'
        r'\.perm_check\s*=\s*NULL'
    )
    s_match = sentinel_pat.search(content, pos)
    if not s_match:
        print("  ERROR: cannot find sentinel entry in dispatch table")
        return False
    # Insert BEFORE the sentinel's opening brace, not before .cmd=0
    # (the regex matches .cmd=0 but the entry also has a preceding {)
    s_pos = content.rfind('{', pos, s_match.start())
    if s_pos < 0:
        print("  ERROR: cannot find sentinel opening brace")
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

    # Declare susfs_init() via extern (not #include) to avoid header resolution issues
    extern_decl = '\nextern void susfs_init(void);\n'
    if 'extern void susfs_init' not in content:
        content = content.replace(
            'extern void __init ksu_lsm_hook_init(void);',
            'extern void __init ksu_lsm_hook_init(void);' + extern_decl,
            1)

    # Insert susfs_init() inside the init function body:
    # 1) Find module_init() to get the function name
    # 2) Find the function definition
    # 3) Find 'return' inside the function
    # 4) Insert before the last return (not after it!)
    # NOTE: banner-based insertion is WRONG because the banner
    # is inside #ifdef CONFIG_KSU_DEBUG -> susfs_init() would
    # be guarded by DEBUG config and disabled in non-debug builds.
    lines = content.split('\n')
    new_lines = []
    inserted = False

    for i, line in enumerate(lines):
        # Skip kernelsu_init_early (conditional stub), target real init
        m = re.match(r'module_init\s*\(\s*kernelsu_init\s*\)\s*;', line.strip())
        if m:
            fn_name = "kernelsu_init"
            # Walk backward to find function definition
            for j in range(i - 1, -1, -1):
                if re.search(r'\b' + re.escape(fn_name) + r'\s*\(', lines[j]):
                    # Found function def at line j. Parse body.
                    brace_depth = 0
                    fn_started = False
                    last_return_line = -1
                    for li in range(j, len(lines)):
                        l = lines[li]
                        for ch in l:
                            if ch == '{':
                                brace_depth += 1
                                fn_started = True
                            elif ch == '}':
                                brace_depth -= 1
                                if fn_started and brace_depth <= 0:
                                    break
                        if not fn_started:
                            continue
                        if brace_depth <= 0:
                            break
                        stripped = l.strip()
                        if stripped.startswith('return ') and stripped.endswith(';'):
                            last_return_line = li
                    if last_return_line > 0:
                        indent = '\t'
                        block = f'\n{indent}/* susfs init */\n{indent}#ifdef CONFIG_KSU_SUSFS\n{indent}    susfs_init();\n{indent}#endif\n'
                        lines.insert(last_return_line, block)
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
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
