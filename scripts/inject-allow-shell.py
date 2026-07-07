#!/usr/bin/env python3
"""
inject-allow-shell.py — 添加 allow_shell 模块参数到 legacy KSU-Next init.c

从 dev 分支移植，允许通过内核 cmdline 或 sysfs 控制 shell 是否获取 root。

可移植的改动：
  1. 添加 `allow_shell` bool 变量（CONFIG_KSU_DEBUG 时默认 true）
  2. 添加 `module_param(allow_shell, bool, 0)` 注册
  3. 在 kernelsu_init() 中添加启动日志

不可移植的改动（不注入）：
  - 将 allow_shell 连接到权限决策逻辑（如 allowlist）
    → workqueue/atomic context 差异，需单独评估
    4.19 上通过 apply-ksu-hooks.py 已连接 manual hook

参考：dev 分支 kernel/core/init.c
"""

import sys
import os
import re

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_ALLOW_SHELL_INJECTED */"


def main():
    init_c = os.path.join(KSU, "core/init.c")
    if not os.path.exists(init_c):
        print(f"ERROR: {init_c} not found")
        sys.exit(1)

    with open(init_c) as f:
        content = f.read()

    if SCRIPT_MARK in content:
        print("SKIP: allow_shell already injected")
        return

    # ---- 1. 添加变量声明 + module_param ----
    # 在 `bool ksu_late_loaded;` 之后注入
    anchor_var = "bool ksu_late_loaded;"
    if anchor_var not in content:
        print("ERROR: cannot find 'bool ksu_late_loaded;' in init.c")
        sys.exit(1)

    var_block = f"""bool ksu_late_loaded;

{SCRIPT_MARK}
#ifdef CONFIG_KSU_DEBUG
bool allow_shell = true;
#else
bool allow_shell = false;
#endif
module_param(allow_shell, bool, 0);
"""

    content = content.replace(anchor_var, var_block, 1)

    # ---- 2. 在 kernelsu_init() 开头添加日志 ----
    # 在 `ksu_feature_init();` 之前注入 `if (allow_shell)` 检查
    anchor_fn = re.compile(
        r'^(\t*)ksu_feature_init\(\);',
        re.MULTILINE
    )
    if not anchor_fn.search(content):
        print("ERROR: cannot find 'ksu_feature_init();' in init.c")
        sys.exit(1)

    log_block = """\\1if (allow_shell)
\\1\\tpr_alert("shell is allowed at init!");
\\1
\\1ksu_feature_init();"""

    content = anchor_fn.sub(log_block, content, 1)

    with open(init_c, 'w') as f:
        f.write(content)

    print("OK: allow_shell module_param injected")
    print("RESULT: init.c now has allow_shell module_param with CONFIG_KSU_DEBUG guard")


if __name__ == '__main__':
    main()
