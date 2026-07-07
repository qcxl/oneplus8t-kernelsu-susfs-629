#!/usr/bin/env python3
"""
inject-selinux-hide.py — 4.19 完整版 selinux_hide 注入脚本

功能：
  1. 清理旧版 Route A (setprocattr-only) 注入残留
  2. 复制 feature/selinux_hide.{c,h} 到 drivers/kernelsu/feature/
  3. 在 core/init.c 添加 ksu_selinux_hide_init/exit 调用
  4. 在 Kbuild 添加 feature/selinux_hide.o
  5. 在 uapi/feature.h 添加 KSU_FEATURE_SELINUX_HIDE 枚举

用法：
  python3 inject-selinux-hide.py <kernel_root>

其中 <kernel_root> 是已经执行过 KernelSU-Next setup.sh 的内核源码根目录。
脚本会在 <kernel_root>/drivers/kernelsu/ 下进行注入。

注意：
  - 与 legacy 分支已有的 KSU_FEATURE_SELINUX_HIDE_STATUS (=4) 共存
  - 本脚本注入的功能使用 KSU_FEATURE_SELINUX_HIDE (=5)
  - fake status page 由 legacy 分支 selinux/selinux.c 中的 ksu_selinux_hide_status_* 提供
  - 本脚本注入的 selinux_hide.c 提供 context_write + access_write + setprocattr 钩子
"""

import sys
import os
import re
import shutil

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
PATCH_DIR = os.path.join(REPO_ROOT, "kernel-patches")

# 标记符号 — 用于幂等性检查
SCRIPT_MARK = "/* KSU_SELINUX_HIDE_V2_INJECTED */"
OLD_SCRIPT_MARK = "/* KSU_SELINUX_HIDE_INJECTED */"

# ============= 通用工具 =============

def log_ok(msg):
    print(f"  OK: {msg}")

def log_skip(msg):
    print(f"  SKIP: {msg}")

def log_err(msg):
    print(f"  ERROR: {msg}")

def log_info(msg):
    print(f"  : {msg}")

def read_file(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return f.read()

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def resolve_ksu(rel_path):
    """在 KSU 目录下解析路径"""
    return os.path.join(KSU, rel_path)

def find_file(root, candidates):
    """在 root 下按候选列表查找第一个存在的文件"""
    for c in candidates:
        p = os.path.join(root, c)
        if os.path.exists(p):
            return p
    return None

def find_feature_h():
    """查找 uapi/feature.h 的实际位置

    setup.sh 后路径可能是:
      - drivers/kernelsu/../uapi/feature.h  (via symlink: KernelSU-Next/uapi/feature.h)
      - drivers/kernelsu/include/uapi/feature.h (via include symlink)
      - drivers/kernelsu/uapi/feature.h (if ksu is real dir with uapi/)
      - uapi/feature.h (when uapi is at kernel root)
      - KernelSU-Next/uapi/feature.h (direct path)
      - KernelSU/kernel/uapi/feature.h (fallback)
    """
    return find_file(KERNEL_ROOT, [
        "drivers/kernelsu/../uapi/feature.h",
        "drivers/kernelsu/include/uapi/feature.h",
        "drivers/kernelsu/uapi/feature.h",
        "uapi/feature.h",
        "KernelSU-Next/uapi/feature.h",
        "KernelSU/kernel/uapi/feature.h",
    ])

# ============= Step 1: 清理旧版 Route A 注入残留 =============

def cleanup_old_injection():
    """移除旧版 inject-selinux-hide.py 注入到 selinux.c 的 Route A 代码"""
    print("[1/5] Cleaning up old Route A injection from selinux.c...")
    selinux_c = resolve_ksu("selinux/selinux.c")
    content = read_file(selinux_c)
    if content is None:
        log_err(f"{selinux_c} not found")
        return False

    if OLD_SCRIPT_MARK not in content:
        log_skip("no old injection found")
        return True

    # 旧版注入格式: 在 ksu_selinux_hide_status_handle_second_stage 之前插入
    # OLD_SCRIPT_MARK + 一大块代码。我们移除从 OLD_SCRIPT_MARK 所在行开始
    # 到下一个 'void ksu_selinux_hide_status_handle_second_stage' 之间的内容
    idx = content.find(OLD_SCRIPT_MARK)
    if idx == -1:
        log_skip("OLD_SCRIPT_MARK not found (already clean)")
        return True

    # 找 OLD_SCRIPT_MARK 所在行的行首
    line_start = content.rfind('\n', 0, idx)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1

    # 找旧注入代码块的结束位置：下一个函数定义 'void ksu_selinux_hide_status_handle_second_stage'
    end_marker = "void ksu_selinux_hide_status_handle_second_stage(void)"
    end_idx = content.find(end_marker, idx)
    if end_idx == -1:
        # 找不到结束标记，回退到文件末尾截断
        new_content = content[:line_start]
        log_info(f"end marker not found, truncating to line {line_start}")
    else:
        # 保留到 end_marker 之前
        new_content = content[:line_start] + content[end_idx:]

    if not new_content.endswith('\n'):
        new_content += '\n'

    write_file(selinux_c, new_content)
    log_ok("removed old Route A injection from selinux.c")
    return True

# ============= Step 2: 复制新文件到 feature/ =============

def copy_source_files():
    """复制 selinux_hide.c 和 selinux_hide.h 到 drivers/kernelsu/feature/"""
    print("[2/5] Copying selinux_hide source files...")
    files = [
        ("feature/selinux_hide.c", "feature/selinux_hide.c"),
        ("feature/selinux_hide.h", "feature/selinux_hide.h"),
    ]
    for src_rel, dst_rel in files:
        # 优先从 kernel-patches/feature/ 读取
        src = os.path.join(PATCH_DIR, src_rel)
        if not os.path.exists(src):
            log_err(f"source not found: {src}")
            return False

        dst = resolve_ksu(dst_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        log_ok(f"copied {dst_rel}")
    return True

# ============= Step 3: 修改 core/init.c =============

def patch_init_c():
    """在 kernelsu_init() 和 kernelsu_exit() 中添加 selinux_hide 调用"""
    print("[3/5] Patching core/init.c...")
    init_c = resolve_ksu("core/init.c")
    content = read_file(init_c)
    if content is None:
        log_err(f"{init_c} not found")
        return False

    if SCRIPT_MARK in content:
        log_skip("init.c already injected")
        return True

    # 添加 #include "feature/selinux_hide.h"
    include_anchor = '#include "selinux/selinux.h"'
    if include_anchor not in content:
        log_err(f"anchor '{include_anchor}' not found in init.c")
        return False
    include_block = f'\n{SCRIPT_MARK}\n#include "feature/selinux_hide.h"'
    content = content.replace(include_anchor, include_anchor + include_block, 1)

    # 统计现有 ksu_selinux_hide_init() 调用次数
    init_call_count = content.count("ksu_selinux_hide_init();")

    # 新版 legacy（commit 430a739 后）init.c 已自带 ksu_selinux_hide_init() 调用
    # 旧版 legacy 需要注入。兼容两种版本。
    if init_call_count >= 2:
        log_ok("init.c already has ksu_selinux_hide_init() calls (legacy was updated)")
    else:
        # 尝试新版函数名，再尝试旧版
        matched = False
        for fn_name in ["ksu_selinux_hide_init", "ksu_selinux_hide_status_init"]:
            pattern = re.compile(r"(\t+)" + fn_name + r"\(\);")
            matches = list(pattern.finditer(content))
            if len(matches) >= 1:
                m = matches[0]
                insert_pos = m.end()
                indent = m.group(1)
                content = content[:insert_pos] + f"\n{indent}ksu_selinux_hide_init();" + content[insert_pos:]
                log_ok(f"added ksu_selinux_hide_init() (flexible, fn={fn_name})")
                matched = True
                # 第二次调用（normal 路径）
                if len(matches) >= 2:
                    m2 = matches[1]
                    insert_pos2 = m2.end()
                    content = content[:insert_pos2] + f"\n{indent}ksu_selinux_hide_init();" + content[insert_pos2:]
                    log_ok(f"added ksu_selinux_hide_init() to normal path (fn={fn_name})")
                break
        if not matched:
            log_err(f"could not find selinux_hide_init anchor in init.c")
            return False

    # 在 kernelsu_exit() 添加 ksu_selinux_hide_exit() 调用
    exit_anchor = "\t// Phase 1: Stop all hooks first to prevent new callbacks\n\tksu_syscall_hook_manager_exit();"
    exit_inject = "\t// Phase 1: Stop all hooks first to prevent new callbacks\n\tksu_selinux_hide_exit();\n\tksu_syscall_hook_manager_exit();"
    if exit_anchor in content:
        content = content.replace(exit_anchor, exit_inject, 1)
        log_ok("added ksu_selinux_hide_exit() to kernelsu_exit()")
    else:
        # 尝试不带注释的锚点
        alt_exit = "ksu_syscall_hook_manager_exit();"
        if alt_exit in content:
            content = content.replace(alt_exit, "ksu_selinux_hide_exit();\n\t" + alt_exit, 1)
            log_ok("added ksu_selinux_hide_exit() (alt anchor)")
        else:
            log_info("exit anchor not found, skipping exit cleanup (non-critical)")

    write_file(init_c, content)
    log_ok("init.c patched")
    return True

# ============= Step 4: 修改 Kbuild =============

def patch_kbuild():
    """在 Kbuild 中添加 feature/selinux_hide.o"""
    print("[4/5] Patching Kbuild...")
    kbuild = resolve_ksu("Kbuild")
    content = read_file(kbuild)
    if content is None:
        log_err(f"{kbuild} not found")
        return False

    if "feature/selinux_hide.o" in content:
        log_skip("Kbuild already has feature/selinux_hide.o")
        return True

    # 在 feature/sucompat.o 后面添加
    anchor = "kernelsu-objs += feature/sucompat.o"
    inject = "kernelsu-objs += feature/sucompat.o\nkernelsu-objs += feature/selinux_hide.o"
    if anchor not in content:
        log_err(f"anchor '{anchor}' not found in Kbuild")
        return False

    content = content.replace(anchor, inject, 1)
    write_file(kbuild, content)
    log_ok("Kbuild patched")
    return True

# ============= Step 5: 修改 uapi/feature.h =============

def patch_feature_h():
    """在 uapi/feature.h 中添加 KSU_FEATURE_SELINUX_HIDE 枚举"""
    print("[5/5] Patching uapi/feature.h...")
    feature_h = find_feature_h()
    if feature_h is None:
        log_err("uapi/feature.h not found in any candidate location")
        return False

    log_info(f"found at: {feature_h}")
    content = read_file(feature_h)
    if content is None:
        log_err(f"cannot read {feature_h}")
        return False

    # 检查是否已有 KSU_FEATURE_SELINUX_HIDE（注意：必须用精确匹配，
    # 因为 KSU_FEATURE_SELINUX_HIDE_STATUS 包含子串 KSU_FEATURE_SELINUX_HIDE）
    # 用正则匹配 " = N," 结尾来精确区分两个枚举
    import re as _re
    has_hide = bool(_re.search(r'KSU_FEATURE_SELINUX_HIDE\s*=\s*\d+', content))
    has_status = bool(_re.search(r'KSU_FEATURE_SELINUX_HIDE_STATUS\s*=\s*\d+', content))

    if has_hide and has_status:
        log_skip("feature.h already has both enums")
        return True

    if has_status and not has_hide:
        # 已有 SELINUX_HIDE_STATUS，只添加 SELINUX_HIDE
        anchor = "KSU_FEATURE_SELINUX_HIDE_STATUS = 4,"
        inject = "/* KSU_FEATURE_SELINUX_HIDE_STATUS = 4 removed */\n    KSU_FEATURE_SELINUX_HIDE = 4, /* selinux_hide: context+access+setprocattr */"
        if anchor not in content:
            log_err(f"anchor '{anchor}' not found in feature.h")
            return False
        content = content.replace(anchor, inject, 1)
        write_file(feature_h, content)
        log_ok("feature.h patched (added KSU_FEATURE_SELINUX_HIDE)")
        return True

    if not has_status and not has_hide:
        # 两个都没有，只添加 SELINUX_HIDE（STATUS 已弃用，HIDE 覆盖其 ID）
        anchors = [
            "KSU_FEATURE_KERNEL_UMOUNT = 1,",
            "KSU_FEATURE_SU_COMPAT = 0,",
        ]
        for anchor in anchors:
            if anchor in content:
                inject = anchor + "\n    KSU_FEATURE_SELINUX_HIDE = 4, /* selinux_hide: context+access+setprocattr (overrides legacy STATUS) */"
                content = content.replace(anchor, inject, 1)
                write_file(feature_h, content)
                log_ok("feature.h patched (added KSU_FEATURE_SELINUX_HIDE=4)")
                return True
        log_err("no suitable anchor found in feature.h")
        return False

    # has_hide but not has_status — 异常情况
    log_info("unexpected state: has SELINUX_HIDE but not SELINUX_HIDE_STATUS")
    return True

# ============= 主流程 =============

def main():
    print("=" * 60)
    print("selinux_hide v2 injector (4.19 complete port)")
    print(f"  target: {KERNEL_ROOT}")
    print(f"  ksu dir: {KSU}")
    print("=" * 60)

    if not os.path.isdir(KSU):
        log_err(f"drivers/kernelsu/ not found at {KSU}")
        log_err("ensure KernelSU-Next setup.sh has been run first")
        sys.exit(1)

    ok = True
    ok &= cleanup_old_injection()
    ok &= copy_source_files()
    ok &= patch_init_c()
    ok &= patch_kbuild()
    ok &= patch_feature_h()

    print("=" * 60)
    if ok:
        print("RESULT: ALL OK")
        print()
        print("selinux_hide v2 injection complete. Feature overview:")
        print("  - KSU_FEATURE_SELINUX_HIDE_STATUS (=4): fake status page (legacy)")
        print("  - KSU_FEATURE_SELINUX_HIDE (=5):       context_write + access_write + setprocattr")
        print()
        print("After boot, check dmesg for:")
        print("  ksu_selinux_hide: initialized (enabled=1, running=1)")
        print("  ksu_selinux_hide: hooked write_op[SEL_CONTEXT]")
        print("  ksu_selinux_hide: hooked write_op[SEL_ACCESS]")
        print("  ksu_selinux_hide: selinux_setprocattr hooked")
    else:
        print("RESULT: SOME FAILURES — review output above")
    print("=" * 60)

    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
