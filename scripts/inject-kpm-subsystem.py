#!/usr/bin/env python3
"""Inject KPM subsystem (kernel/kpm/ files + IOCTL #102/#200) into legacy KernelSU-Next source tree."""

import os
import sys

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
KPM_SRC = os.path.join(os.path.dirname(__file__), "..", "kernel-patches", "kpm")
KSU_DIR = os.path.join(KERNEL_DIR, "drivers", "kernelsu")

def inject_kpm_files():
    """Copy kpm/ source files into drivers/kernelsu/kpm/"""
    kpm_dst = os.path.join(KSU_DIR, "kpm")
    os.makedirs(kpm_dst, exist_ok=True)
    for f in ["kpm.c", "kpm.h", "compact.c", "compact.h", "super_access.c", "super_access.h"]:
        src = os.path.join(KPM_SRC, f)
        dst = os.path.join(kpm_dst, f)
        if os.path.exists(src):
            with open(src) as fin:
                content = fin.read()
            with open(dst, "w") as fout:
                fout.write(content)
            print(f"  Copied {f}")
        else:
            print(f"  WARNING: {f} not found in {KPM_SRC}")

def modify_kbuild():
    """Add kpm/*.o to Kbuild"""
    kbuild = os.path.join(KSU_DIR, "Kbuild")
    with open(kbuild) as f:
        content = f.read()
    if "kpm/" in content:
        print("  Kbuild: kpm entries already exist, skipping")
        return
    # Add after sulog entry or before infra/
    marker = "kernelsu-objs += infra/file_wrapper.o"
    if marker in content:
        insertion = (
            "\nifeq ($(CONFIG_KPM),y)\n"
            "kernelsu-objs += kpm/compact.o\n"
            "kernelsu-objs += kpm/kpm.o\n"
            "kernelsu-objs += kpm/super_access.o\n"
            "endif\n"
        )
        content = content.replace(marker, insertion + marker)
        with open(kbuild, "w") as f:
            f.write(content)
        print("  Kbuild: added kpm/*.o entries")
    else:
        print("  WARNING: marker 'kernelsu-objs += infra/file_wrapper.o' not found in Kbuild")

def modify_supercall_h():
    """Add IOCTL #102 (ENABLE_KPM) and #200 (KPM) to supercall.h"""
    # supercall.h is at KSU repo root uapi/, NOT inside drivers/kernelsu/uapi/.
    # Match the search pattern used by inject-sukisu-ioctls.py.
    sh = None
    for candidate in [
        os.path.join(KSU_DIR, "../uapi/supercall.h"),      # KSU-root/uapi/supercall.h (via symlink)
        os.path.join(KERNEL_DIR, "../uapi/supercall.h"),    # build-repo-root/uapi/supercall.h
        os.path.join(KSU_DIR, "include/uapi/supercall.h"),  # via symlink: .../include/uapi/
        "KernelSU-Next/uapi/supercall.h",                    # direct path (legacy CI)
    ]:
        path = os.path.normpath(os.path.join(KERNEL_DIR, candidate)) if not os.path.isabs(candidate) else candidate
        if os.path.exists(path):
            sh = path
            print(f"  Found supercall.h at: {sh}")
            break
    if not sh:
        print(f"  WARNING: supercall.h not found")
        return
    with open(sh) as f:
        content = f.read()
    if "KSU_IOCTL_ENABLE_KPM" in content:
        print("  supercall.h: KPM IOCTLs already exist, skipping")
        return
    # Add after HOOK_TYPE definition
    insertion = (
        "static const __u32 KSU_IOCTL_ENABLE_KPM = _IOC(_IOC_READ, 'K', 102, 0);\n"
        "static const __u32 KSU_IOCTL_KPM = _IOC(_IOC_READ | _IOC_WRITE, 'K', 200, 0);\n\n"
        "struct ksu_enable_kpm_cmd {\n"
        "    __u8 enabled;\n"
        "};\n\n"
        "struct ksu_kpm_cmd {\n"
        "    __u64 control_code;\n"
        "    __u64 arg1;\n"
        "    __u64 arg2;\n"
        "    __u64 result_code;\n"
        "};\n\n"
        "static const __u32 SUKISU_KPM_LOAD = 1;\n"
        "static const __u32 SUKISU_KPM_UNLOAD = 2;\n"
        "static const __u32 SUKISU_KPM_NUM = 3;\n"
        "static const __u32 SUKISU_KPM_LIST = 4;\n"
        "static const __u32 SUKISU_KPM_INFO = 5;\n"
        "static const __u32 SUKISU_KPM_CONTROL = 6;\n"
        "static const __u32 SUKISU_KPM_VERSION = 7;\n"
    )

    def _apply_patch(path):
        with open(path) as f:
            c = f.read()
        if "KSU_IOCTL_ENABLE_KPM" in c:
            return  # already patched
        marker = "static const __u32 KSU_IOCTL_HOOK_TYPE"
        if marker in c:
            c = c.replace(marker, insertion + marker)
        else:
            c = c.rstrip()
            if c.endswith("#endif"):
                c = c[:-len("#endif")] + insertion + "\n#endif"
        with open(path, "w") as f:
            f.write(c)
        print(f"  supercall.h: patched {path}")

    _apply_patch(sh)

    # Also patch drivers/kernelsu/uapi/supercall.h if different (compiler uses this path)
    alt_path = os.path.join(KSU_DIR, "uapi/supercall.h")
    if os.path.exists(alt_path) and os.path.abspath(alt_path) != os.path.abspath(sh):
        _apply_patch(alt_path)
        print(f"  supercall.h: also patched {alt_path}")

def modify_dispatch_c():
    """Add KPM IOCTL handlers to dispatch.c"""
    dc = os.path.join(KSU_DIR, "supercall", "dispatch.c")
    if not os.path.exists(dc):
        print(f"  WARNING: dispatch.c not found")
        return
    with open(dc) as f:
        content = f.read()
    if "do_enable_kpm" in content:
        print("  dispatch.c: KPM handlers already exist, skipping")
        return
    # Add handler function after do_get_hook_type
    handler_func = (
        "\nstatic int do_enable_kpm(void __user *arg)\n"
        "{\n"
        "    struct ksu_enable_kpm_cmd cmd;\n"
        "    cmd.enabled = IS_ENABLED(CONFIG_KPM);\n"
        "    if (copy_to_user(arg, &cmd, sizeof(cmd)))\n"
        "        return -EFAULT;\n"
        "    return 0;\n"
        "}\n"
    )
    marker = "static int do_get_hook_mode"
    if marker in content:
        content = content.replace(marker, handler_func + "\n" + marker)
    # Add IOCTL mapping entries before sentinel
    ioctl_entries = (
        "    {\n"
        "        .cmd = KSU_IOCTL_ENABLE_KPM,\n"
        "        .name = \"GET_ENABLE_KPM\",\n"
        "        .handler = do_enable_kpm,\n"
        "        .perm_check = manager_or_root\n"
        "    },\n"
        "#ifdef CONFIG_KPM\n"
        "    {\n"
        "        .cmd = KSU_IOCTL_KPM,\n"
        "        .name = \"KPM_OPERATION\",\n"
        "        .handler = do_kpm,\n"
        "        .perm_check = manager_or_root\n"
        "    },\n"
        "#endif\n"
    )
    sentinel_marker = "{0, NULL, NULL, NULL} // Sentinel"
    alt_sentinel = ".cmd = 0,\n        .name = NULL,\n        .handler = NULL,\n        .perm_check = NULL"
    if sentinel_marker in content:
        content = content.replace(sentinel_marker, ioctl_entries + "    " + sentinel_marker)
    elif alt_sentinel in content:
        content = content.replace(alt_sentinel, ioctl_entries.rstrip() + "\n    " + alt_sentinel)
    with open(dc, "w") as f:
        f.write(content)
    print("  dispatch.c: added KPM IOCTL handlers")

def main():
    inject_kpm_files()
    modify_kbuild()
    modify_supercall_h()
    modify_dispatch_c()
    print("\nKPM injection complete")

if __name__ == "__main__":
    main()
