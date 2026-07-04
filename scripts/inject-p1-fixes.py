#!/usr/bin/env python3
"""
inject-p1-fixes.py — P1 零散修复

实际差异检查结果（2026-07-03）：
- seccomp reset: legacy 4.19 路径正确（put_seccomp_filter），仅 GFP_ATOMIC→GFP_KERNEL
- throne OOB: DT_DIR|DT_UNKNOWN 和 GFP_KERNEL 已存在
- umount 隔离: is_zygote 逻辑已在 legacy 中
- selinux RCU: stop_machine 是 4.19 正确做法
"""

import sys, os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")
SCRIPT_MARK = "/* KSU_P1_INJECTED */"

def main():
    print("[P1 fixes] target=%s" % KERNEL_ROOT)

    app_c = os.path.join(KSU, "policy/app_profile.c")
    if not os.path.exists(app_c):
        print(f"  ERROR: {app_c} not found"); sys.exit(1)

    with open(app_c) as f: c = f.read()
    if SCRIPT_MARK in c:
        print("  SKIP: already injected")
    else:
        c = c.replace("GFP_ATOMIC", "GFP_KERNEL")
        c += "\n/* KSU_P1_INJECTED */\n"
        with open(app_c, 'w') as f: f.write(c)
        print("  FIX: GFP_ATOMIC → GFP_KERNEL")
        print("  OK: %s" % app_c)

    print("  Result: ALL OK")
    sys.exit(0)

if __name__ == '__main__':
    main()