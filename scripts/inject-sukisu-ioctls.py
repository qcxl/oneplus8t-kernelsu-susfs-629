#!/usr/bin/env python3
"""Inject SukiSU-Ultra IOCTL handlers (#100 GET_FULL_VERSION, #101 HOOK_TYPE)
into KernelSU-Next legacy branch source tree.

Idempotent — safe to run multiple times.
"""

import sys, os, re

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
KSU_DIR = os.path.join(KERNEL_DIR, "drivers/kernelsu")

# Code to inject into supercall.h (before closing #endif)
SUPERCALL_H_ADDITIONS = """
static const __u32 KSU_IOCTL_GET_FULL_VERSION = _IOC(_IOC_READ, 'K', 100, 0);
static const __u32 KSU_IOCTL_HOOK_TYPE = _IOC(_IOC_READ, 'K', 101, 0);

// SukiSU-Ultra compat structs
struct ksu_get_full_version_cmd {
    char version_full[255]; // Output: full version string
};

struct ksu_hook_type_cmd {
    char hook_type[32]; // Output: hook type string
};
"""

# Code to inject into dispatch.c (before the IOCTL handler table comment)
DISPATCH_HANDLERS = """
static int do_get_full_version(void __user *arg)
{
    struct ksu_get_full_version_cmd cmd = { 0 };

    strscpy(cmd.version_full, KSU_VERSION_FULL, sizeof(cmd.version_full));

    if (copy_to_user(arg, &cmd, sizeof(cmd))) {
        pr_err("get_full_version: copy_to_user failed\\n");
        return -EFAULT;
    }

    return 0;
}

static int do_get_hook_type(void __user *arg)
{
    struct ksu_hook_type_cmd cmd = { 0 };
    const char *type = "Tracepoint Syscall Redirect";

    strscpy(cmd.hook_type, type, sizeof(cmd.hook_type));

    if (copy_to_user(arg, &cmd, sizeof(cmd))) {
        pr_err("get_hook_type: copy_to_user failed\\n");
        return -EFAULT;
    }

    return 0;
}

"""

DISPATCH_MAPPING_ENTRIES = """    {
        .cmd = KSU_IOCTL_GET_FULL_VERSION,
        .name = "GET_FULL_VERSION",
        .handler = do_get_full_version,
        .perm_check = always_allow
    },
    {
        .cmd = KSU_IOCTL_HOOK_TYPE,
        .name = "GET_HOOK_TYPE",
        .handler = do_get_hook_type,
        .perm_check = manager_or_root
    },
"""


def sp_find_supercall_h():
    """supercall.h is at KSU repo root uapi/, NOT inside drivers/kernelsu/uapi/.
    Check multiple paths like fix-ksu-uapi-v2.py does."""
    candidates = [
        os.path.join(KSU_DIR, "../uapi/supercall.h"),      # via symlink: KSU-root/uapi/supercall.h
        os.path.join(KSU_DIR, "include/uapi/supercall.h"),  # via symlink: .../include/uapi/
        os.path.join(KERNEL_DIR, "../uapi/supercall.h"),    # direct from kernel dir up
        "KernelSU-Next/uapi/supercall.h",                    # direct path (legacy CI)
    ]
    abs_candidates = [os.path.normpath(os.path.join(KERNEL_DIR, c)) if not os.path.isabs(c) else c for c in candidates]
    # Also check KSU_DIR itself for a direct uapi/ subdir
    abs_candidates.append(os.path.normpath(os.path.join(KSU_DIR, "uapi/supercall.h")))

    for p in abs_candidates:
        if os.path.exists(p):
            return p
    return None

def patch_supercall_h():
    target = sp_find_supercall_h()
    if not target:
        print(f"SKIP: supercall.h not found (checked: drivers/kernelsu/../uapi/, drivers/kernelsu/uapi/)")
        return False

    with open(target, "r") as f:
        content = f.read()

    if "KSU_IOCTL_GET_FULL_VERSION" in content:
        print(f"OK: {target} already has KSU_IOCTL_GET_FULL_VERSION")
        return True

    # Find the last #endif and insert before it
    lines = content.split("\n")
    insert_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "#endif":
            insert_idx = i
            break

    if insert_idx < 0:
        print(f"ERROR: cannot find #endif in {target}")
        return False

    # Insert before #endif
    new_lines = lines[:insert_idx] + [SUPERCALL_H_ADDITIONS.strip()] + lines[insert_idx:]
    with open(target, "w") as f:
        f.write("\n".join(new_lines))

    rel = os.path.relpath(target, KERNEL_DIR)
    print(f"PATCHED: {rel} — added structs + IOCTL defs before #endif")
    return True


def patch_dispatch_c_handlers():
    target = os.path.join(KSU_DIR, "supercall/dispatch.c")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found")
        return False

    with open(target, "r") as f:
        content = f.read()

    if "do_get_full_version" in content:
        print(f"OK: {target} already has do_get_full_version")
        return True

    # Find the anchor: "// IOCTL handlers mapping table"
    anchors = [
        "// IOCTL handlers mapping table",
        "static const struct ksu_ioctl_cmd_map ksu_ioctl_handlers[] = {",
    ]

    for anchor in anchors:
        if anchor in content:
            content = content.replace(
                anchor,
                DISPATCH_HANDLERS.strip() + "\n\n" + anchor,
                1,
            )
            with open(target, "w") as f:
                f.write(content)
            print(f"PATCHED: {target} — added handler functions before '{anchor[:40]}'")
            return True

    print(f"ERROR: cannot find anchor in {target}")
    return False


def patch_dispatch_c_mapping():
    target = os.path.join(KSU_DIR, "supercall/dispatch.c")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found")
        return False

    with open(target, "r") as f:
        content = f.read()

    if "KSU_IOCTL_GET_FULL_VERSION" in content and "KSU_IOCTL_HOOK_TYPE" in content:
        print(f"OK: {target} already has KSU_IOCTL mapping entries")
        return True

    # The sentinel is always the last entry: .cmd = 0, .name = NULL
    # Match the complete sentinel block before the closing of the array
    sentinel_markers = [
        # Tab-indented (dev branch style)
        '\t{\n\t\t.cmd = 0,\n\t\t.name = NULL,\n\t\t.handler = NULL,\n\t\t.perm_check = NULL\n\t} // Sentinel',
        # Space-indented (common style)
        '    {\n        .cmd = 0,\n        .name = NULL,\n        .handler = NULL,\n        .perm_check = NULL\n    } // Sentinel',
        # Tab, single line
        '\t{ .cmd = 0, .name = NULL, .handler = NULL, .perm_check = NULL } // Sentinel',
        # Space, single line
        '    { .cmd = 0, .name = NULL, .handler = NULL, .perm_check = NULL } // Sentinel',
    ]

    for marker in sentinel_markers:
        if marker in content:
            content = content.replace(marker, DISPATCH_MAPPING_ENTRIES + marker, 1)
            with open(target, "w") as f:
                f.write(content)
            print(f"PATCHED: {target} — added mapping entries before sentinel")
            return True

    # Flexible fallback: find the last '.cmd = 0, .name = NULL' pattern
    import re

    # Get last occurrence of .cmd = 0 with .name = NULL nearby
    last_cmd = content.rfind('.cmd = 0')
    last_name = content.rfind('.name = NULL')
    if last_cmd > 0 and last_name > last_cmd:
        # Find the opening { before .cmd = 0
        # Walk backwards from .cmd to find '{'
        open_brace = content.rfind('{', 0, last_cmd)
        if open_brace > 0:
            # Find the closing of this sentinel block: '} // Sentinel'
            sentinel_end = content.find('} // Sentinel', last_cmd)
            if sentinel_end > 0:
                sentinel_block = content[open_brace:sentinel_end + len('} // Sentinel')]
                print(f"DEBUG: found sentinel via flexible match: {repr(sentinel_block[:80])}...")
                content = content.replace(sentinel_block, DISPATCH_MAPPING_ENTRIES.strip() + '\n' + sentinel_block, 1)
                with open(target, "w") as f:
                    f.write(content)
                print(f"PATCHED: {target} — added mapping entries (flexible match)")
                return True

    print(f"ERROR: cannot find sentinel in {target}")
    return False


def patch_ksu_h():
    """Add KSU_VERSION_FULL fallback if missing."""
    candidates = [
        os.path.join(KSU_DIR, "include/ksu.h"),
        os.path.join(KSU_DIR, "ksu.h"),
    ]

    for target in candidates:
        if not os.path.exists(target):
            continue
        with open(target, "r") as f:
            content = f.read()

        if "KSU_VERSION_FULL" in content:
            print(f"OK: {target} already has KSU_VERSION_FULL")
            return

        fallback = '\n#ifndef KSU_VERSION_FULL\n#define KSU_VERSION_FULL KSU_VERSION_TAG "+dev"\n#endif\n'
        content += fallback
        with open(target, "w") as f:
            f.write(content)
        print(f"PATCHED: {target} — added KSU_VERSION_FULL fallback")
        return

    print(f"WARNING: no ksu.h found in {KSU_DIR}")


ok = True
ok &= patch_supercall_h()
ok &= patch_dispatch_c_handlers()
ok &= patch_dispatch_c_mapping()
patch_ksu_h()

if not ok:
    print("ERROR: one or more patches failed")
    sys.exit(1)
else:
    print("All SukiSU-Ultra IOCTL patches applied successfully")
