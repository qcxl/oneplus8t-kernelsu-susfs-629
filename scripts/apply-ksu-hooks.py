#!/usr/bin/env python3
"""Apply KSU manual hook source patches to kernel source files."""

import sys, os, re

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."

INCLUDES = {
    "fs/open.c": '#include <linux/ksu.h>\n',
    "fs/exec.c": '#include <linux/ksu.h>\n',
    "fs/read_write.c": '#include <linux/ksu.h>\n',
}

HOOKS = [
    {
        "file": "fs/open.c",
        "func_pattern": r"^long do_faccessat\(int dfd",
        "code": '\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n',
    },
    {
        "file": "fs/exec.c",
        "func_pattern": r"^static int __do_execve_file\(int fd",
        "code": '\tksu_handle_execveat(&fd, &filename->name, NULL, NULL, &flags);\n',
    },
    {
        "file": "fs/read_write.c",
        "func_pattern": r"^ssize_t vfs_read\(struct file \*file,",
        "code": '\tksu_handle_vfs_read(&file, &buf, &count, &pos);\n',
    },
]

VAR_DECL_RE = re.compile(
    r'^\s*(?:struct |const |int |char |void |size_t |ssize_t |long |unsigned |'
    r'static |bool |u8 |u16 |u32 |u64 |__u8 |__u16 |__u32 |__u64 |'
    r'atomic_t |wait_queue_head_t |spinlock_t |mutex )'
)

def add_include(filepath, include_line):
    filepath = os.path.join(KERNEL_DIR, filepath)
    if not os.path.exists(filepath):
        return False
    with open(filepath) as f:
        content = f.read()
    if '#include <linux/ksu.h>' in content:
        return True
    lines = content.split('\n')
    last_include = -1
    for i, line in enumerate(lines):
        if line.startswith('#include'):
            last_include = i
    if last_include < 0:
        return False
    lines.insert(last_include + 1, include_line.strip())
    with open(filepath, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  [OK] Include: {filepath}")
    return True

def insert_hook(filepath, func_pattern, hook_code):
    filepath = os.path.join(KERNEL_DIR, filepath)
    if not os.path.exists(filepath):
        print(f"  [SKIP] {filepath} not found")
        return False

    with open(filepath) as f:
        lines = f.readlines()

    result = []
    i = 0
    hooked = False
    in_func = False
    found_brace = False

    while i < len(lines):
        line = lines[i]

        if not in_func:
            if re.match(func_pattern, line):
                in_func = True
                found_brace = False
            result.append(line)
        elif not found_brace:
            if '{' in line:
                found_brace = True
            result.append(line)
        else:
            stripped = line.strip()
            is_blank = stripped == ''
            is_var_decl = bool(VAR_DECL_RE.match(stripped))

            if is_blank or is_var_decl:
                result.append(line)
            else:
                guard_open = '#ifdef CONFIG_KSU\n'
                guard_close = '#endif /* CONFIG_KSU */\n'
                result.append(guard_open)
                result.append(hook_code)
                result.append(guard_close)
                result.append(line)
                hooked = True
                in_func = False
                print(f"  [OK] Hook: {filepath}:~{i+1}")
        i += 1

    if hooked:
        with open(filepath, 'w') as f:
            f.writelines(result)
    else:
        print(f"  [WARN] No hook point: {filepath}")
    return hooked

def main():
    for fp, inc in INCLUDES.items():
        add_include(fp, inc)
    for hook in HOOKS:
        insert_hook(hook["file"], hook["func_pattern"], hook["code"])
    print("\n=== Verification ===")
    for hook in HOOKS:
        fp = os.path.join(KERNEL_DIR, hook["file"])
        if os.path.exists(fp):
            count = sum(1 for l in open(fp) if "ksu_handle_" in l)
            sym = hook["code"].strip().split("(")[0]
            print(f"  {sym}: {'OK' if count > 0 else 'MISSING!'}")

if __name__ == "__main__":
    main()
