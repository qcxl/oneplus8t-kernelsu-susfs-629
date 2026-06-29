#!/usr/bin/env python3
"""Apply KSU manual hook source patches to kernel source files.
Inserts ksu_handle_* calls at the correct positions in syscall functions."""

import sys
import os
import re

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."

HOOKS = [
    {
        "file": "fs/open.c",
        "target": r"^long do_faccessat\(int dfd",
        "code": '\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);',
    },
    {
        "file": "fs/exec.c",
        "target": r"^static int do_execveat_common\(int fd,",
        "code": '\tksu_handle_execveat(&fd, &filename->name, NULL, NULL, &flags);',
    },
    {
        "file": "fs/read_write.c",
        "target": r"^ssize_t vfs_read\(struct file \*file,",
        "code": '\tksu_handle_vfs_read(&file, &buf, &count, &pos);',
    },
]

def apply_hook(filepath, target_pattern, hook_code):
    filepath = os.path.join(KERNEL_DIR, filepath)
    if not os.path.exists(filepath):
        print(f"  SKIP: {filepath} not found")
        return False

    with open(filepath, 'r') as f:
        lines = f.readlines()

    result = []
    hooked = False
    i = 0
    while i < len(lines):
        result.append(lines[i])
        # Check if current line matches the function signature
        if re.match(target_pattern, lines[i]):
            # Find the opening brace (may be on same line or next line)
            brace_line = i
            if '{' not in lines[brace_line]:
                for j in range(i + 1, min(i + 5, len(lines))):
                    if '{' in lines[j]:
                        brace_line = j
                        # Add all lines up to and including the brace
                        for k in range(i + 1, brace_line + 1):
                            result.append(lines[k])
                            i = k
                        break
                else:
                    continue  # No brace found, skip
            # Now brace_line has the opening brace
            # Insert the hook code after the brace
            indent = '\t'  # kernel uses tabs
            guard_open = f'#ifdef CONFIG_KSU\n'
            guard_close = f'#endif /* CONFIG_KSU */\n'
            result.append(guard_open)
            result.append(hook_code + '\n')
            result.append(guard_close)
            hooked = True
            print(f"  ✅ Hook inserted: {filepath}:~{brace_line+1}")
        i += 1

    if hooked:
        with open(filepath, 'w') as f:
            f.writelines(result)
    else:
        print(f"  ⚠️  No match: {filepath} / {target_pattern}")

    return hooked

def main():
    success = True
    for hook in HOOKS:
        ok = apply_hook(hook["file"], hook["target"], hook["code"])
        if not ok:
            success = False

    # Verify
    print("\n=== Verification ===")
    for hook in HOOKS:
        filepath = os.path.join(KERNEL_DIR, hook["file"])
        if os.path.exists(filepath):
            count = 0
            with open(filepath) as f:
                for line in f:
                    if "ksu_handle_" in line and "CONFIG_KSU" not in line:
                        count += 1
            symbol = hook["code"].strip().split("(")[0]
            print(f"  {symbol}: {'✅' if count > 0 else '❌'} found in {hook['file']}")

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
