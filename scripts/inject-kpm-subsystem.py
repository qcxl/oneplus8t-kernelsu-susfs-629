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
    # Try multiple locations: KSU_DIR/uapi, KERNEL_DIR/uapi, cwd/uapi
    candidates = [
        os.path.join(KSU_DIR, "uapi", "supercall.h"),
        os.path.join(KERNEL_DIR, "uapi", "supercall.h"),
        os.path.join(os.getcwd(), "uapi", "supercall.h"),
    ]
    # Also check if KSU_DIR has a uapi/ at the repo root (via ../../uapi/)
    repo_root = os.path.normpath(os.path.join(KSU_DIR, ".."))
    candidates.append(os.path.join(repo_root, "uapi", "supercall.h"))
    # Try one level further up (KSU_DIR is drivers/kernelsu, repo root is ../..)
    repo_root2 = os.path.normpath(os.path.join(KSU_DIR, "..", ".."))
    if repo_root2 != repo_root:
        candidates.append(os.path.join(repo_root2, "uapi", "supercall.h"))

    sh = None
    for c in candidates:
        if os.path.exists(c):
            sh = c
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
    marker = "static const __u32 KSU_IOCTL_HOOK_TYPE"
    if marker in content:
        content = content.replace(marker, insertion + marker)
    else:
        # fallback: add before #endif
        content = content.rstrip()
        if content.endswith("#endif"):
            content = content[:-len("#endif")] + insertion + "\n#endif"
    with open(sh, "w") as f:
        f.write(content)
    print("  supercall.h: added KPM IOCTL definitions")

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
