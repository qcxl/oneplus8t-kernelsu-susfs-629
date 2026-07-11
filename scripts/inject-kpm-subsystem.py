#!/usr/bin/env python3
"""Inject KPM subsystem (kernel/kpm/ files + IOCTL #102/#200) into legacy KernelSU-Next source tree."""

import os
import sys

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
KPM_SRC = os.path.join(os.path.dirname(__file__), "..", "kernel-patches", "kpm")
KSU_DIR = os.path.join(KERNEL_DIR, "drivers", "kernelsu")

def inject_kpm_files():
    """Copy kpm/ source files into drivers/kernelsu/kpm/ and fix include paths for KSUN tree layout"""
    kpm_dst = os.path.join(KSU_DIR, "kpm")
    os.makedirs(kpm_dst, exist_ok=True)
    for f in ["kpm.c", "kpm.h", "compact.c", "compact.h", "super_access.c", "super_access.h"]:
        src = os.path.join(KPM_SRC, f)
        dst = os.path.join(kpm_dst, f)
        if os.path.exists(src):
            with open(src) as fin:
                content = fin.read()
            # Fix include paths: SukiSU-Ultra tree uses sibling dirs (policy/, manager/, infra/...)
            # while KSUN tree nests these under drivers/kernelsu/, so kpm/ needs ../ prefix.
            if f == "kpm.h":
                content = content.replace(
                    '#include "uapi/supercall.h"',
                    '#include "../uapi/supercall.h"'
                )
            elif f == "compact.c":
                content = content.replace(
                    '#include "infra/symbol_resolver.h"',
                    '#include "../infra/symbol_resolver.h"'
                )
                content = content.replace(
                    '#include "policy/allowlist.h"',
                    '#include "../policy/allowlist.h"'
                )
                content = content.replace(
                    '#include "manager/manager_identity.h"',
                    '#include "../manager/manager_identity.h"'
                )
            with open(dst, "w") as fout:
                fout.write(content)
            print(f"  Copied {f}" + (" (includes fixed)" if f in ("kpm.h", "compact.c") else ""))
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
            "\nkernelsu-objs += kpm/compact.o\n"
            "kernelsu-objs += kpm/kpm.o\n"
            "kernelsu-objs += kpm/super_access.o\n"
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
    # Add include for kpm.h (declares do_kpm).  dispatch.c is at drivers/kernelsu/supercall/,
    # kpm.h is at drivers/kernelsu/kpm/kpm.h, so we need "../kpm/kpm.h".
    if '#include "../kpm/kpm.h"' not in content:
        # Find the last #include line to insert after it
        lines = content.split('\n')
        last_include_idx = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('#include'):
                last_include_idx = i
        if last_include_idx >= 0:
            lines.insert(last_include_idx + 1, '#include "../kpm/kpm.h"')
            content = '\n'.join(lines)
            print("  dispatch.c: added #include \"../kpm/kpm.h\"")
        else:
            print("  WARNING: no #include found in dispatch.c, could not add kpm.h header")
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
    # Add IOCTL mapping entries before sentinel (use flexible matching like inject-sukisu-ioctls.py)
    ioctl_entries = (
        "    {\n"
        "        .cmd = KSU_IOCTL_ENABLE_KPM,\n"
        "        .name = \"GET_ENABLE_KPM\",\n"
        "        .handler = do_enable_kpm,\n"
        "        .perm_check = manager_or_root\n"
        "    },\n"
        "    {\n"
        "        .cmd = KSU_IOCTL_KPM,\n"
        "        .name = \"KPM_OPERATION\",\n"
        "        .handler = do_kpm,\n"
        "        .perm_check = manager_or_root\n"
        "    },\n"
    )
    sentinel_markers = [
        ".cmd = 0,\n        .name = NULL,\n        .handler = NULL,\n        .perm_check = NULL",
        ".cmd = 0,\n        .name = NULL,\n        .handler = NULL,\n        .perm_check",
        ".cmd = 0,\n        .name = NULL,\n        .handler = NULL,",
        ".cmd = 0,\n        .name = NULL,",
        ".cmd = 0,",
    ]
    injected = False
    for marker in sentinel_markers:
        last_cmd = content.rfind(marker)
        if last_cmd >= 0:
            open_brace = content.rfind('{', 0, last_cmd)
            if open_brace >= 0:
                sentinel_end = content.find('} // Sentinel', last_cmd)
                if sentinel_end > 0:
                    sentinel_block = content[open_brace:sentinel_end + len('} // Sentinel')]
                    content = content.replace(sentinel_block, ioctl_entries.rstrip() + "\n" + sentinel_block, 1)
                    injected = True
                    print("  dispatch.c: added KPM IOCTL mapping entries (flexible match)")
                    break
    if not injected:
        print("  WARNING: sentinel not found, KPM mapping entries NOT added")
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
