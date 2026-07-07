#!/usr/bin/env python3
"""
inject-susfs-sdcard-monitor.py — 移植 sdcard 监听（v2.2.0 → 4.19）

移植内容：
  1. 复制 susfs_sdcard_monitor.c 到 kernel/fs/
  2. 在 fs/Makefile 添加编译条目
  3. 在 include/linux/susfs.h 添加函数声明（如尚未存在）

要求：
  - KernelSU-Next setup.sh 已执行
  - SUSFS v1.5.5 已安装（susfs.c, susfs.h, susfs_def.h 已就位）
"""

import sys
import os
import shutil

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
PATCH_DIR = os.path.join(REPO_ROOT, "kernel-patches")

SRC_FILE = os.path.join(PATCH_DIR, "feature", "susfs_sdcard_monitor.c")
DST_FILE = os.path.join(KERNEL_ROOT, "fs", "susfs_sdcard_monitor.c")
DECL = "void susfs_start_sdcard_monitor_fn(void);"


def main():
    ok = True

    # 1. Copy source file
    if not os.path.exists(SRC_FILE):
        print(f"ERROR: source not found: {SRC_FILE}")
        sys.exit(1)

    os.makedirs(os.path.dirname(DST_FILE), exist_ok=True)
    shutil.copy2(SRC_FILE, DST_FILE)
    print(f"  COPY: {DST_FILE}")

    # 2. Add to fs/Makefile
    makefile = os.path.join(KERNEL_ROOT, "fs", "Makefile")
    if not os.path.exists(makefile):
        print(f"ERROR: {makefile} not found")
        sys.exit(1)

    with open(makefile) as f:
        mf = f.read()

    entry = "obj-y += susfs_sdcard_monitor.o"
    if entry not in mf:
        # Add after the last obj-y entry or after the "# SUSFS" block if it exists
        if "# SUSFS" in mf:
            anchor = "# SUSFS"
            mf = mf.replace(anchor, f"{anchor}\n{entry}", 1)
        else:
            anchor = "obj-y += notify/"
            if anchor in mf:
                mf = mf.replace(anchor, f"{entry}\n{anchor}", 1)
            else:
                # Append to end of file
                mf += f"\n# SDCard monitor (SUSFS v2.2.0)\n{entry}\n"
        with open(makefile, 'w') as f:
            f.write(mf)
        print(f"  MAKEFILE: added {entry}")
    else:
        print(f"  SKIP: {entry} already in Makefile")

    # 3. Add declaration to include/linux/susfs.h
    susfs_h = os.path.join(KERNEL_ROOT, "include", "linux", "susfs.h")
    if not os.path.exists(susfs_h):
        print(f"WARNING: {susfs_h} not found, declaration not added")
    else:
        with open(susfs_h) as f:
            content = f.read()
        if DECL not in content:
            # Find the forward declaration section
            for anchor in ["void susfs_set_avc_log_spoofing", "void susfs_init", "int susfs"]:
                if anchor in content:
                    content = content.replace(anchor, f"{DECL}\n{anchor}", 1)
                    print(f"  HEADER: added declaration to {susfs_h}")
                    break
            else:
                # Append before the last #endif
                if "#endif" in content:
                    content = content.replace("#endif", f"{DECL}\n\n#endif", 1)
                    print(f"  HEADER: added declaration (end of file)")
            with open(susfs_h, 'w') as f:
                f.write(content)
        else:
            print(f"  SKIP: declaration already in susfs.h")

    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
