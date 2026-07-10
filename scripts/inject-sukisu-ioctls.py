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


def patch_supercall_h():
    target = os.path.join(KSU_DIR, "uapi/supercall.h")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found")
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

    print(f"PATCHED: {target} — added structs + IOCTL defs before #endif")
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

    # Find the sentinel (last entry before closing brace of the array)
    # Pattern: .cmd = 0, .name = NULL, .handler = NULL
    sentinel_patterns = [
        re.compile(r'\s*\.cmd\s*=\s*0\s*,\s*$'),
    ]

    lines = content.split("\n")
    sentinel_line = -1
    for i in range(len(lines) - 1, -1, -1):
        if '.cmd = 0' in lines[i] and (i + 1 < len(lines) and '.name = NULL' in lines[i + 1]):
            # Found the sentinel start line
            sentinel_line = i
            break

    if sentinel_line < 0:
        print(f"ERROR: cannot find sentinel in {target}")
        return False

    # Insert mapping entries before the sentinel
    new_lines = lines[:sentinel_line] + [DISPATCH_MAPPING_ENTRIES.strip()] + lines[sentinel_line:]
    with open(target, "w") as f:
        f.write("\n".join(new_lines))

    print(f"PATCHED: {target} — added mapping entries before sentinel")
    return True


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
