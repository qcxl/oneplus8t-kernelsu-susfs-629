#!/usr/bin/env python3
"""
inject-setuid-hook.py — 简化 legacy setuid_hook.c（部分同步 dev）

可移植的改动：
  1. 用 spin_lock_irq(&current->sighand->siglock) 保护 seccomp_cache 操作
     （dev 的做法，避免并发竞争）

不可移植的改动（不注入）：
  - 直接调用 ksu_install_fd() 替代 task_work_add
    → legacy 仍用 kprobe，setresuid handler 在 atomic context，直接调用会睡眠
    → dev 已迁移到 syscall_table hook（不在 atomic context），legacy 不能照搬
  - 函数签名变更
    → 会破坏 hook_manager.c 的调用方
  - tp_marker 相关
    → legacy 已在 hook_manager.c 内联实现，保留 #ifdef KSU_KPROBES_HOOK 即可

风险点：
  - 低。仅添加 spin_lock 保护，不改控制流
  - spin_lock_irq 在 4.19 可用，sighand->siglock 是标准字段

参考：dev 分支 kernel/hook/setuid_hook.c
"""

import sys
import os
import re

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_SETUID_HOOK_SIMPLIFIED */"


def main():
    setuid_c = os.path.join(KSU, "hook/setuid_hook.c")
    if not os.path.exists(setuid_c):
        print(f"ERROR: {setuid_c} not found")
        sys.exit(1)

    with open(setuid_c) as f:
        content = f.read()

    if SCRIPT_MARK in content:
        print("SKIP: setuid_hook.c already simplified")
        return

    # 用正则匹配，处理空白差异（tab vs space）
    # 匹配模式：ksu_seccomp_allow_cache(current->seccomp.filter, __NR_reboot);
    # 在它之前插入 spin_lock_irq，之后插入 spin_unlock_irq
    #
    # 但要避免双重注入：只在 #if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0) 块内注入
    # 简化做法：找到所有 ksu_seccomp_allow_cache 调用，用正则替换

    # 模式：可选空白 + if (current->seccomp.mode == ...) { \n 空白 + ksu_seccomp_allow_cache(...) \n 空白 + }
    pattern = re.compile(
        r'(^[ \t]*if \(current->seccomp\.mode == SECCOMP_MODE_FILTER && current->seccomp\.filter\) \{\n)'
        r'([ \t]*ksu_seccomp_allow_cache\(current->seccomp\.filter, __NR_reboot\);\n)'
        r'([ \t]*\})',
        re.MULTILINE
    )

    matches = list(pattern.finditer(content))
    if not matches:
        print("ERROR: no ksu_seccomp_allow_cache call sites found")
        sys.exit(1)

    # 检查是否已经注入过（通过查找 spin_lock_irq 近旁）
    if "spin_lock_irq(&current->sighand->siglock);" in content:
        print("SKIP: spin_lock already present")
        return

    # 对每个匹配，在其前面加 spin_lock_irq，后面加 spin_unlock_irq
    # 从后往前替换，避免偏移问题
    new_content = content
    for m in reversed(matches):
        indent_line = m.group(1)  # "        if (...) {\n"
        call_line = m.group(2)    # "        ksu_seccomp_allow_cache(...);\n"
        close_brace = m.group(3)  # "        }"

        # 提取缩进
        indent = re.match(r'^([ \t]*)', call_line).group(1)

        replacement = (
            f"{indent_line}"
            f"{indent}spin_lock_irq(&current->sighand->siglock);\n"
            f"{call_line}"
            f"{indent}spin_unlock_irq(&current->sighand->siglock);\n"
            f"{close_brace}"
        )

        new_content = new_content[:m.start()] + replacement + new_content[m.end():]

    # 在文件开头添加标记（在第一个 #include 之前）
    new_content = new_content.replace(
        "#include <linux/compiler.h>",
        f"{SCRIPT_MARK}\n#include <linux/compiler.h>",
        1
    )

    with open(setuid_c, 'w') as f:
        f.write(new_content)

    print(f"OK: wrapped {len(matches)} ksu_seccomp_allow_cache call(s) with spin_lock_irq")
    print("RESULT: setuid_hook.c simplified (spin_lock protection added)")
    print("        task_work_add for ksu_install_fd() KEPT (atomic context safe)")


if __name__ == '__main__':
    main()
