#!/usr/bin/env python3
"""Apply KSU manual hook source patches - uses extern declarations."""

import sys, os, re

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."

# Extern declarations to add (the KSU header path isn't available in-tree)
EXTERNS = (
    '\n'
    '/* KernelSU manual hook declarations (KSUN-legacy compatible) */\n'
    'extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode, int *flags);\n'
    'extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags);\n'
    'extern int ksu_handle_vfs_read(struct file **file_ptr, char __user **buf_ptr, size_t *count_ptr, loff_t **pos);\n'
    'extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);\n'
)

INCLUDES = {}  # Not used - extern declarations serve the same purpose

HOOKS = [
    {
        "file": "fs/open.c",
        "func_pattern": r"^long do_faccessat\(int dfd",
        "code": '\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n',
    },
    {
        "file": "fs/exec.c",
        "func_pattern": r"^static int __do_execve_file\(int fd",
        "code": '\tksu_handle_execveat(&fd, &filename, NULL, NULL, &flags);\n',
    },
    {
        "file": "fs/read_write.c",
        "func_pattern": r"^ssize_t vfs_read\(struct file \*file,",
        "code": '\tksu_handle_vfs_read(&file, &buf, &count, &pos);\n',
    },
]

VAR_DECL_RE = re.compile(
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
    r'unsigned |signed'
    r')'
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
                result.append(hook_code)
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
                extern_block = '\nextern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);\n'
                lines.insert(last_include + 1, extern_block)
                content = '\n'.join(lines)

            # Hook inside SYSCALL_DEFINE4(reboot...) AFTER variable declarations
            # (C89 requires declarations before statements) but BEFORE the
            # CAP_SYS_BOOT check and LINUX_REBOOT_MAGIC1 check.
            # The KSU Manager (non-root app) doesn't have CAP_SYS_BOOT, so
            # the hook must run before that check to install the KSU fd.
            marker = '\t/* We only trust the superuser with rebooting the system. */'
            hook = (
                '\t/* KSU hook: short-circuit for KSU management commands */\n'
                '\tif (IS_ENABLED(CONFIG_KSU) && magic1 == 0xDEADBEEF) {\n'
                '\t\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n'
                '\t\treturn 0;\n'
                '\t}\n'
                '\n'
                '\t/* We only trust the superuser with rebooting the system. */'
            )
            if marker in content:
                content = content.replace(marker, hook, 1)
                with open(reboot_path, 'w') as f:
                    f.write(content)
                print(f"  [OK] Hook in SYSCALL_DEFINE4(reboot): {reboot_path}")
            else:
                print(f"  [WARN] SYSCALL_DEFINE4(reboot) marker not found")

    # For kernel/sys.c (prctl syscall), add prctl hook
    sys_path = os.path.join(KERNEL_DIR, "kernel", "sys.c")
    if os.path.exists(sys_path):
        with open(sys_path) as f:
            content = f.read()
        if 'ksu_handle_prctl' not in content:
            lines = content.split('\n')
            last_include = -1
            for i, line in enumerate(lines):
                if line.startswith('#include'):
                    last_include = i
            if last_include >= 0:
                extern_block = '\nextern int ksu_handle_prctl(int option, unsigned long arg2, unsigned long arg3, unsigned long arg4, unsigned long arg5);\nextern int ksu_debug_manager_appid;\n'
                lines.insert(last_include + 1, extern_block)
                content = '\n'.join(lines)

            # Hook inside SYSCALL_DEFINE5(prctl...) BEFORE the switch(option).
            marker = '\terror = 0;\n\tswitch (option) {'
            hook = (
                '\terror = 0;'
                '\n\t/* KSU hook: handle prctl(0xDEADBEEF, ...) for manager fd */'
                '\n\tif (IS_ENABLED(CONFIG_KSU) && option == 0xDEADBEEF) {'
                '\n\t\treturn ksu_handle_prctl(option, arg2, arg3, arg4, arg5);'
                '\n\t}'
                '\n\t/* KSU hook: skip PR_SET_SECCOMP for manager app (libc uses prctl for seccomp) */'
                '\n\tif (IS_ENABLED(CONFIG_KSU) && option == PR_SET_SECCOMP &&'
                '\n\t    ksu_debug_manager_appid >= 0 &&'
                '\n\t    ksu_debug_manager_appid == (int)current_uid().val) {'
                '\n\t\treturn 0;'
                '\n\t}'
                '\n\tswitch (option) {'
            )
            if marker in content:
                content = content.replace(marker, hook, 1)
                with open(sys_path, 'w') as f:
                    f.write(content)
                print(f"  [OK] Hook in SYSCALL_DEFINE5(prctl): {sys_path}")
            else:
                print(f"  [WARN] SYSCALL_DEFINE5(prctl) marker not found")
        else:
            print(f"  prctl hook already present, skipping")

    # Standard insert_hook for the other files
    for hook in HOOKS:
        insert_hook(hook["file"], hook["func_pattern"], hook["code"])

    # Verification
    print("\n=== Verification ===")
    for hook in HOOKS:
        fp = os.path.join(KERNEL_DIR, hook["file"])
        count = sum(1 for l in open(fp) if "ksu_handle_" in l) if os.path.exists(fp) else 0
        sym = hook["code"].strip().split("(")[0]
        print(f"  {sym}: {'OK' if count > 0 else 'MISSING!'}")
    # Verify reboot.c separately
    rp = os.path.join(KERNEL_DIR, "kernel", "reboot.c")
    if os.path.exists(rp):
        rc = sum(1 for l in open(rp) if "ksu_handle_sys_reboot" in l)
        print(f"  ksu_handle_sys_reboot: {'OK' if rc >= 1 else 'MISSING!'}")
    # Verify sys.c separately
    sp = os.path.join(KERNEL_DIR, "kernel", "sys.c")
    if os.path.exists(sp):
        sc = sum(1 for l in open(sp) if "ksu_handle_prctl" in l)
        print(f"  ksu_handle_prctl: {'OK' if sc >= 1 else 'MISSING!'}")

if __name__ == "__main__":
    main()
