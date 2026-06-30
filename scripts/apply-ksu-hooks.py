#!/usr/bin/env python3
"""Apply KSU manual hook source patches - uses extern declarations."""

import sys, os, re

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."

# Extern declarations to add (the KSU header path isn't available in-tree)
EXTERNS = (
    '\n'
    '/* KernelSU manual hook - inserted by build script */\n'
    '#ifdef CONFIG_KSU\n'
    'extern void ksu_handle_faccessat(int *dfd, const char __user **filename, int *mode, void *);\n'
    'extern void ksu_handle_execveat(int *fd, const char __user **filename, void *argv, void *envp, int *flags);\n'
    'extern void ksu_handle_vfs_read(struct file **file, char __user **buf, size_t *count, loff_t **pos);\n'
    'extern void ksu_handle_sys_reboot(void *);\n'
    '#endif\n'
)

INCLUDES = {
    "fs/open.c": '#include <linux/ksu.h>\n',
    "fs/exec.c": '#include <linux/ksu.h>\n',
    "fs/read_write.c": '#include <linux/ksu.h>\n',
    "kernel/reboot.c": '#include <linux/ksu.h>\n',
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
    {
        "file": "kernel/reboot.c",
        "func_pattern": r"^static int __orderly_poweroff\|^void orderly_poweroff",
        "code": '\tksu_handle_sys_reboot(NULL);\n',
    },
]

VAR_DECL_RE = re.compile(
    r'^\s*(?:struct |const |int |char |void |size_t |ssize_t |long |unsigned |'
    r'static |bool |u8 |u16 |u32 |u64 |__u8 |__u16 |__u32 |__u64 |'
    r'atomic_t |wait_queue_head_t |spinlock_t |mutex )'
)

def add_externs(filepath, extern_text):
    """Add extern declarations after the last #include line."""
    filepath = os.path.join(KERNEL_DIR, filepath)
    if not os.path.exists(filepath):
        return False
    with open(filepath) as f:
        content = f.read()
    if 'ksu_handle_faccessat' in content:
        return True  # Already added
    lines = content.split('\n')
    last_include = -1
    for i, line in enumerate(lines):
        if line.startswith('#include'):
            last_include = i
    if last_include < 0:
        return False
    lines.insert(last_include + 1, '')
    lines.insert(last_include + 2, extern_text)
    with open(filepath, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  [OK] Externs: {filepath}")
    return True

def insert_hook(filepath, func_pattern, hook_code):
    filepath = os.path.join(KERNEL_DIR, filepath)
    if not os.path.exists(filepath):
        print(f"  [SKIP] {filepath}")
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
                guard = '#ifdef CONFIG_KSU\n'
                end = '#endif /* CONFIG_KSU */\n'
                result.append(guard)
                result.append(hook_code)
                result.append(end)
                result.append(line)
                hooked = True
                in_func = False
                print(f"  [OK] Hook: {filepath}:~{i+1}")
        i += 1

    if hooked:
        with open(filepath, 'w') as f:
            f.writelines(result)
    else:
        print(f"  [WARN] No hook: {filepath}")
    return hooked

def main():
    for fp in ["fs/open.c", "fs/exec.c", "fs/read_write.c"]:
        add_externs(fp, EXTERNS)

    # For kernel/reboot.c, use direct string replacement (more reliable)
    reboot_path = os.path.join(KERNEL_DIR, "kernel", "reboot.c")
    if os.path.exists(reboot_path):
        with open(reboot_path) as f:
            content = f.read()
        # Check if hook already added
        if 'ksu_handle_sys_reboot' not in content:
            # Add extern declaration after last #include
            lines = content.split('\n')
            last_include = -1
            for i, line in enumerate(lines):
                if line.startswith('#include'):
                    last_include = i
            if last_include >= 0:
                extern_block = '\n#ifdef CONFIG_KSU\nextern void ksu_handle_sys_reboot(void *);\n#endif /* CONFIG_KSU */\n'
                lines.insert(last_include + 1, extern_block)
                content = '\n'.join(lines)

            # Add hook call inside __orderly_poweroff
            marker = 'static int __orderly_poweroff(bool force)\n{'
            hook = '\n#ifdef CONFIG_KSU\n\tksu_handle_sys_reboot(NULL);\n#endif /* CONFIG_KSU */\n'
            if marker in content:
                insert_pos = content.index(marker) + len(marker)
                content = content[:insert_pos] + hook + content[insert_pos:]
                with open(reboot_path, 'w') as f:
                    f.write(content)
                print(f"  [OK] Hook: {reboot_path}")
            else:
                print(f"  [WARN] No __orderly_poweroff in reboot.c")
        else:
            print(f"  [OK] Hook already in reboot.c")
    else:
        print(f"  [SKIP] reboot.c not found")

    # Standard insert_hook for the other files
    for hook in HOOKS:
        insert_hook(hook["file"], hook["func_pattern"], hook["code"])
    print("\n=== Verification ===")
    for hook in HOOKS:
        fp = os.path.join(KERNEL_DIR, hook["file"])
        count = sum(1 for l in open(fp) if "ksu_handle_" in l) if os.path.exists(fp) else 0
        sym = hook["code"].strip().split("(")[0]
        print(f"  {sym}: {'OK' if count > 0 else 'MISSING!'}")

if __name__ == "__main__":
    main()
