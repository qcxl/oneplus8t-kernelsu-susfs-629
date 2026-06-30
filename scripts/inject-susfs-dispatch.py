#!/usr/bin/env python3
"""
inject-susfs-dispatch.py - Inject SUSFS dispatch glue into KernelSU-Next legacy.

Usage: python3 inject-susfs-dispatch.py <kernel-root>

Adds:
1. #include <linux/susfs.h> to core/main.c (after last existing #include)
2. SUSFS prctl dispatch block inside ksu_handle_prctl() in core/main.c
3. #include + susfs_init() call to the init file (core/init.c or ksu.c)

Returns 0 on success, 1 if any injection failed.
"""

import sys, os, re


def path_exists(root, *paths):
    for p in paths:
        if os.path.exists(os.path.join(root, p)):
            return p
    return None


def add_include_after_last(content, header):
    """Insert '#include <header>' after the last #include line in content."""
    lines = content.split('\n')
    last_include_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('#include'):
            last_include_idx = i
    if last_include_idx >= 0:
        indent = '' if not lines[last_include_idx][:1].isspace() else lines[last_include_idx][:len(lines[last_include_idx]) - len(lines[last_include_idx].lstrip())]
        lines.insert(last_include_idx + 1, f'{indent}#include <{header}>')
        return '\n'.join(lines), True
    # No #include found at all - insert at top
    lines.insert(0, f'#include <{header}>')
    return '\n'.join(lines), True


def find_fn_boundary(content, fn_regex, start_from=0):
    """
    Find a function definition matching fn_regex and return (start_line, brace_open_line).
    Looks for 'regex(' on a line, then finds the opening '{'.
    """
    match = re.search(fn_regex, content[start_from:])
    if not match:
        return None, None
    fn_start = start_from + match.start()
    # Find the opening brace after the function signature
    search_from = fn_start
    brace_pos = content.find('{', search_from)
    if brace_pos < 0:
        return None, None
    # The line containing the fn signature
    line_start = content.rfind('\n', 0, fn_start) + 1 if fn_start > 0 else 0
    return line_start, brace_pos


def find_last_return_in_fn(content, fn_open_brace):
    """Find the position of the last 'return' before the closing '}' of a function."""
    brace_depth = 1
    pos = fn_open_brace + 1
    last_return_pos = -1
    while pos < len(content) and brace_depth > 0:
        c = content[pos]
        if c == '{':
            brace_depth += 1
        elif c == '}':
            brace_depth -= 1
        elif brace_depth == 1 and content[pos:pos+7] == '\n\treturn' or content[pos:pos+6] == '\nreturn':
            last_return_pos = pos
        pos += 1
    return last_return_pos


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

    # 1. Add include <linux/susfs.h>
    if '<linux/susfs.h>' not in content:
        content, ok = add_include_after_last(content, 'linux/susfs.h')
        if not ok:
            print("  ERROR: could not add include to init file")
            return False

    # 2. Find the init function's module_init and insert before it
    #    Or insert inside the init function after the banner print
    lines = content.split('\n')
    new_lines = []
    inserted = False
    banner_patterns = [
        re.compile(r'(pr_alert|pr_info|printk)\s*\(.*KernelSU'),
        re.compile(r'pr_info\s*\(\s*"KernelSU'),
        re.compile(r'pr_alert\s*\(\s*"\*.*KernelSU'),
    ]
    for line in lines:
        new_lines.append(line)
        if not inserted and any(p.search(line) for p in banner_patterns):
            indent = ' ' * max(4, len(line) - len(line.lstrip()))
            new_lines.append(f'{indent}#ifdef CONFIG_KSU_SUSFS')
            new_lines.append(f'{indent}    susfs_init();')
            new_lines.append(f'{indent}#endif')
            inserted = True

    if not inserted:
        # Fallback: find function named by module_init and insert inside it
        # Parse module_init(...) to get the function name
        for i, line in enumerate(lines):
            m = re.match(r'module_init\s*\(\s*(\w+)\s*\)\s*;', line.strip())
            if m:
                fn_name = m.group(1)
                # Find the function definition: look backwards for fn_name(
                for j in range(i - 1, -1, -1):
                    if re.search(r'\b' + re.escape(fn_name) + r'\s*\(', lines[j]):
                        # Found the function. Now find its closing brace.
                        fn_text = '\n'.join(lines[j:])
                        brace_depth = 0
                        started = False
                        close_pos_in_fn = -1
                        for k, ch in enumerate(fn_text):
                            if ch == '{':
                                brace_depth += 1
                                started = True
                            elif ch == '}':
                                brace_depth -= 1
                                if started and brace_depth == 0:
                                    close_pos_in_fn = j + fn_text[:k].count('\n')
                                    break
                        if close_pos_in_fn > 0:
                            # Insert just before the closing brace
                            indent = '\t'
                            block = f'\n{indent}/* susfs init */\n{indent}#ifdef CONFIG_KSU_SUSFS\n{indent}    susfs_init();\n{indent}#endif\n'
                            lines.insert(close_pos_in_fn, block)
                            inserted = True
                            new_lines = lines
                        break
                break

    content = '\n'.join(new_lines)
    if not inserted:
        # Last resort: match '}' before module_init
        print("  WARNING: no banner/module_init function found, trying brace search...")
        match = re.search(r'\n\}\s*\n.*module_init\b', content)
        if match:
            pos = content.find('}', match.start()) + 1
            block = '\n#ifdef CONFIG_KSU_SUSFS\n    susfs_init();\n#endif\n'
            content = content[:pos] + block + content[pos:]
            inserted = True

    if not inserted:
        print("  ERROR: could not find insertion point for susfs_init()")
        return False

    with open(init_path, 'w') as f:
        f.write(content)
    print(f"  Init: susfs_init() added to {init_path}")
    return True


def patch_core_main(kernel_root):
    """Add SUSFS dispatch code to the prctl handler in core/main.c."""
    candidates = [
        "drivers/kernelsu/core/main.c",
        "drivers/kernelsu/core_hook.c",
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
        print("  ERROR: no core/main.c found")
        return False

    with open(main_path) as f:
        content = f.read()
    if "CMD_SUSFS_ADD_SUS_PATH" in content:
        print(f"  Dispatch: already present in {main_path}")
        return True

    # 1. Add include <linux/susfs.h> (and <linux/susfs_def.h> for CMD_ constants)
    for hdr in ['linux/susfs.h', 'linux/susfs_def.h']:
        if hdr not in content:
            content, ok = add_include_after_last(content, hdr)
            if not ok:
                print(f"  ERROR: could not add include <{hdr}>")
                return False

    # 2. Find ksu_handle_prctl function and its parameter names
    fn_start, fn_brace = find_fn_boundary(content, r'int\s+ksu_handle_prctl\b')

    if fn_brace is None:
        fn_start, fn_brace = find_fn_boundary(content, r'\bksu_handle_prctl\b')

    if fn_brace is None:
        print("  ERROR: could not find ksu_handle_prctl() function in main.c")
        return False

    # Read function signature from fn_start to fn_brace to detect parameter names
    fn_sig = content[fn_start:fn_brace].strip()
    # Determine parameter variable names from signature
    if 'arg3' in fn_sig:
        p_arg2, p_arg3 = 'arg2', 'arg3'
    elif 'data1' in fn_sig:
        p_arg2, p_arg3 = 'data1', 'data2'
    else:
        # Generic fallback: find the last 2 or 3 parameter names
        p_arg2, p_arg3 = 'arg2', 'arg3'

    # 3. Build the dispatch block (uses detected param names)
    dispatch_block = (
        '\n#ifdef CONFIG_KSU_SUSFS\n'
        '\tif (current_uid().val == 0) {\n'
        f'\t\tvoid __user *uarg = (void __user *){p_arg3};\n'
        f'\t\tswitch ({p_arg2}) {{\n'
        '\t\tcase CMD_SUSFS_ADD_SUS_PATH:\n'
        '\t\t\tsusfs_add_sus_path((struct st_susfs_sus_path __user *)uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_ADD_SUS_MOUNT:\n'
        '\t\t\tsusfs_add_sus_mount((struct st_susfs_sus_mount __user *)uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_ADD_SUS_KSTAT:\n'
        '\t\t\tsusfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_UPDATE_SUS_KSTAT:\n'
        '\t\t\tsusfs_update_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_SET_UNAME:\n'
        '\t\t\tsusfs_set_uname((struct st_susfs_uname __user *)uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_ADD_OPEN_REDIRECT:\n'
        '\t\t\tsusfs_add_open_redirect((struct st_susfs_open_redirect __user *)uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_ENABLE_LOG:\n'
        f'\t\t\tsusfs_set_log((int){p_arg3});\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG:\n'
        '\t\t\tsusfs_set_cmdline_or_bootconfig((char __user *)uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_SHOW_VERSION:\n'
        '\t\t\tif (copy_to_user(uarg, SUSFS_VERSION, strlen(SUSFS_VERSION)+1))\n'
        '\t\t\t\tpr_err("susfs: copy_to_user failed\\n");\n'
        '\t\t\treturn 0;\n'
        '\t\tdefault:\n'
        '\t\t\tbreak;\n'
        '\t\t}\n'
        '\t}\n'
        '#endif /* CONFIG_KSU_SUSFS */\n\n'
    )

    # 4. Find insertion point: after variable declarations but before first statement
    #    (C89/gnu89 requires declarations before statements in a block)
    after_brace = fn_brace + 1
    # Find the end of the brace line
    nl = content.find('\n', fn_brace)
    after_open = nl + 1 if nl >= 0 else after_brace

    # Scan for first non-blank, non-declaration line
    rest = content[after_open:]
    VAR_START_RE = re.compile(
        r'^\s*(?:'
        r'struct |const |enum |union |static |extern |inline |'
        r'int |char |void |long |short |float |double |'
        r'size_t |ssize_t |bool |'
        r'u8 |u16 |u32 |u64 |s8 |s16 |s32 |s64 |'
        r'__u8 |__u16 |__u32 |__u64 |'
        r'pid_t |uid_t |gid_t |loff_t |ktime_t |sector_t |'
        r'dev_t |ino_t |mode_t |nlink_t |blkcnt_t |'
        r'atomic_t |wait_queue_head_t |spinlock_t |mutex |'
        r'vm_flags_t |gfp_t |fmode_t |'
        r'unsigned |signed |'
        r')'
    )
    lines_rest = rest.split('\n')
    skip = 0
    for line in lines_rest:
        stripped = line.strip()
        if stripped == '' or stripped.startswith('/*') or stripped.startswith('*') or stripped.startswith('//'):
            skip += 1
        elif VAR_START_RE.match(stripped):
            skip += 1
        else:
            break

    insert_offset = sum(len(l) + 1 for l in lines_rest[:skip])
    insert_pos = after_open + insert_offset
    before = content[:insert_pos]
    after = content[insert_pos:]
    content = before + dispatch_block + after

    with open(main_path, 'w') as f:
        f.write(content)
    print(f"  Dispatch: added SUSFS prctl dispatch to {main_path}")
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
    ok &= patch_core_main(root)
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
