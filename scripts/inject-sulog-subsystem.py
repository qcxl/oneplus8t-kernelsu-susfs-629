#!/usr/bin/env python3
"""
inject-sulog-subsystem.py — 移植 event_queue + sulog 到 legacy 4.19
- 复制 event_queue.c/h 到 infra/
- 复制 sulog event.c/h + fd.c/h 到 sulog/
- 复制 feature/sulog.c/h 到 feature/
- 替换 tiny_sulog.o → sulog 子系统
- 应用 4.19 兼容补丁 (strncpy_from_user_nofault → strncpy_from_user)
"""

import sys, os, shutil

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")
KBUILD = os.path.join(KSU, "Kbuild")

# 源文件目录（相对于 scripts/ 所在的仓库根目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
PATCH_DIR = os.path.join(REPO_ROOT, "kernel-patches")

FILES = [
    ("event_queue/event_queue.h", "infra/event_queue.h"),
    ("event_queue/event_queue.c", "infra/event_queue.c"),
    ("feature/sulog.h", "feature/sulog.h"),
    ("feature/sulog.c", "feature/sulog.c"),
    ("sulog/event.h", "sulog/event.h"),
    ("sulog/event.c", "sulog/event.c"),
    ("sulog/fd.h", "sulog/fd.h"),
    ("sulog/fd.c", "sulog/fd.c"),
    ("uapi/sulog.h", "include/uapi/sulog.h"),
    # tiny_sulog compatibility wrapper — replaces legacy tiny_sulog.c
    ("tiny_sulog_compat.c", "tiny_sulog.c"),
]

def main():
    ok = True
    print("[sulog-subsystem] target=%s" % KERNEL_ROOT)

    # 1. Copy source files
    for src_rel, dst_rel in FILES:
        src = os.path.join(PATCH_DIR, src_rel)
        dst = os.path.join(KSU, dst_rel)
        dst_dir = os.path.dirname(dst)
        if not os.path.exists(src):
            print(f"  ERROR: source {src} not found")
            ok = False
            continue
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  COPY: {dst_rel}")

    # 2. Update Kbuild: replace tiny_sulog.o with sulog subsystem
    if not os.path.exists(KBUILD):
        print(f"  ERROR: Kbuild not found at {KBUILD}")
        sys.exit(1)

    with open(KBUILD) as f:
        kb = f.read()

    changes = []

    # Replace tiny_sulog.o → keep name but add new sulog subsystem
    if "tiny_sulog.o" in kb:
        # tiny_sulog.o stays (now points to compat wrapper)
        # add new sulog subsystem + event_queue
        additions = (
            "kernelsu-objs += infra/event_queue.o\n"
            "kernelsu-objs += feature/sulog.o\n"
            "kernelsu-objs += sulog/event.o\n"
            "kernelsu-objs += sulog/fd.o"
        )
        kb = kb.replace("kernelsu-objs += tiny_sulog.o",
                         "kernelsu-objs += tiny_sulog.o\n" + additions)
        changes.append("added sulog subsystem + event_queue to Kbuild (kept tiny_sulog.o)")
    else:
        print("  WARNING: tiny_sulog.o not found in Kbuild, adding sulog entries anyway")
        # Add after feature/sucompat.o or similar location
        kb = kb.replace(
            "kernelsu-objs += feature/sulog.o",
            "kernelsu-objs += feature/sulog.o\n"
            "kernelsu-objs += sulog/event.o\n"
            "kernelsu-objs += sulog/fd.o"
        )

    # Add event_queue if not present
    if "event_queue.o" not in kb:
        # Find a good insertion point (after infra/)
        if "kernelsu-objs += infra/file_wrapper.o" in kb:
            kb = kb.replace(
                "kernelsu-objs += infra/file_wrapper.o",
                "kernelsu-objs += infra/file_wrapper.o\n"
                "kernelsu-objs += infra/event_queue.o"
            )
            changes.append("infra/event_queue.o added to Kbuild")

    with open(KBUILD, 'w') as f:
        f.write(kb)

    for c in changes:
        print(f"  KBUILD: {c}")

    # 3. Add KSU_FEATURE_SULOG to uapi/feature.h if missing
    feature_h = os.path.join(KSU, "include/uapi/feature.h")
    if os.path.exists(feature_h):
        with open(feature_h) as f:
            fh = f.read()
        if "KSU_FEATURE_SULOG" not in fh and "SELINUX_HIDE_STATUS = 4" in fh:
            fh = fh.replace(
                "KSU_FEATURE_SELINUX_HIDE_STATUS = 4,",
                "KSU_FEATURE_SULOG = 2,\n\tKSU_FEATURE_ADB_ROOT = 3,\n\tKSU_FEATURE_SELINUX_HIDE_STATUS = 4,"
            )
            with open(feature_h, 'w') as f:
                f.write(fh)
            print("  FEATURE_H: added KSU_FEATURE_SULOG + ADB_ROOT")

    # 4. Apply 4.19 compatibility patches
    event_c = os.path.join(KSU, "sulog/event.c")
    if os.path.exists(event_c):
        with open(event_c) as f:
            ec = f.read()
        ec = ec.replace("strncpy_from_user_nofault(", "strncpy_from_user(")
        ec = ec.replace("ksu_strncpy_from_user(", "strncpy_from_user(")
        # minmax.h was added in 5.1, use kernel.h in 4.19
        ec = ec.replace("#include <linux/minmax.h>", "#include <linux/kernel.h>")
        with open(event_c, 'w') as f:
            f.write(ec)
        print("  COMPAT: strncpy_from_user_nofault → strncpy_from_user")
        print("  COMPAT: linux/minmax.h → linux/kernel.h")

    print("  Result: %s" % ("ALL OK" if ok else "SOME FAILURES"))
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()