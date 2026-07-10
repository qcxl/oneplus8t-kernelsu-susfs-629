#!/usr/bin/env python3
"""Inject SukiSU-Ultra IOCTL handlers (#100 GET_FULL_VERSION, #101 HOOK_TYPE)
into KernelSU-Next legacy branch source tree.

Idempotent — safe to run multiple times.
"""

import sys, os

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
KSU_DIR = os.path.join(KERNEL_DIR, "drivers/kernelsu")

PATCHES = [
    # === supercall.h ===
    {
        "file": os.path.join(KSU_DIR, "uapi/supercall.h"),
        "guard": "KSU_IOCTL_GET_FULL_VERSION",
        "anchor_after": "KSU_IOCTL_DISABLE_ESCAPE_TO_ROOT",
        "inject": """
static const __u32 KSU_IOCTL_GET_FULL_VERSION = _IOC(_IOC_READ, 'K', 100, 0);
static const __u32 KSU_IOCTL_HOOK_TYPE = _IOC(_IOC_READ, 'K', 101, 0);

// SukiSU-Ultra compat structs
struct ksu_get_full_version_cmd {
    char version_full[255]; // Output: full version string
};

struct ksu_hook_type_cmd {
    char hook_type[32]; // Output: hook type string
};

#endif""",
    },
    # === dispatch.c: handler functions (before do_get_hook_mode or ioctl_handlers[]) ===
    {
        "file": os.path.join(KSU_DIR, "supercall/dispatch.c"),
        "guard": "do_get_full_version",
        "anchor_before": "// IOCTL handlers mapping table",
        "inject": """
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

""",
    },
]


def apply_patch(patch):
    target = patch["file"]
    if not os.path.exists(target):
        print(f"SKIP: {target} not found")
        return

    with open(target, "r") as f:
        content = f.read()

    if patch["guard"] in content:
        print(f"OK: {target} already has {patch['guard']}")
        return

    if "anchor_before" in patch:
        if patch["anchor_before"] not in content:
            print(f"ERROR: anchor '{patch['anchor_before']}' not found in {target}")
            return
        content = content.replace(patch["anchor_before"], patch["inject"].lstrip("\n") + "\n" + patch["anchor_before"], 1)
        print(f"PATCHED: {target} — added before '{patch['anchor_before']}'")

    elif "anchor_after" in patch:
        if patch["anchor_after"] not in content:
            print(f"ERROR: anchor '{patch['anchor_after']}' not found in {target}")
            return
        old = patch["anchor_after"]
        # Restore the #endif that we're replacing
        content = content.replace(old, old + "\n" + patch["inject"].replace("#endif\n#endif", "#endif"), 1)
        print(f"PATCHED: {target} — added after '{patch['anchor_after']}'")

    else:
        print(f"ERROR: no anchor specified for {target}")
        return

    with open(target, "w") as f:
        f.write(content)


def apply_mapping_entries():
    """Add mapping table entries to dispatch.c before the sentinel."""
    target = os.path.join(KSU_DIR, "supercall/dispatch.c")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found")
        return

    with open(target, "r") as f:
        content = f.read()

    guard = "KSU_IOCTL_GET_FULL_VERSION"
    if guard in content:
        print(f"OK: {target} already has {guard}")
        return

    # Find the sentinel entry: .cmd = 0,
    # Look for: { .cmd = 0, .name = NULL, .handler = NULL, .perm_check = NULL }
    sentinel_markers = [
        '    {\n        .cmd = 0,\n        .name = NULL,\n        .handler = NULL,\n        .perm_check = NULL\n    } // Sentinel',
        '\t{\n\t\t.cmd = 0,\n\t\t.name = NULL,\n\t\t.handler = NULL,\n\t\t.perm_check = NULL\n\t} // Sentinel',
        '\t{ .cmd = 0, .name = NULL, .handler = NULL, .perm_check = NULL } // Sentinel',
    ]

    new_entries = """    {
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

    for marker in sentinel_markers:
        if marker in content:
            content = content.replace(marker, new_entries + marker, 1)
            with open(target, "w") as f:
                f.write(content)
            print(f"PATCHED: {target} — added mapping entries")
            return

    # Try a more flexible sentinel search
    import re
    # Match the last occurrence of .cmd = 0, .name = NULL
    pattern = r'(\s*\.cmd\s*=\s*0\s*,\s*\.name\s*=\s*NULL)'
    matches = list(re.finditer(pattern, content))
    if not matches:
        print(f"ERROR: cannot find sentinel in {target}")
        return

    # Find the sentinel block: the last match is part of the last entry
    last_match = matches[-1]
    # Find the opening brace
    start = content.rfind('{', 0, last_match.start())
    if start < 0:
        print(f"ERROR: cannot find sentinel brace in {target}")
        return

    sentinel_block = content[start:]
    # Find where Sentinel ends
    end_marker = sentinel_block.find('// Sentinel')
    if end_marker < 0:
        # Try finding the closing brace
        brace_count = 0
        for i, c in enumerate(sentinel_block):
            if c == '{':
                brace_count += 1
            elif c == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_marker = i + 1
                    break
        if end_marker < 0:
            print(f"ERROR: cannot find sentinel end in {target}")
            return

    sentinel_full = sentinel_block[:end_marker + 1]
    content = content.replace(sentinel_full, new_entries + sentinel_full, 1)
    with open(target, "w") as f:
        f.write(content)
    print(f"PATCHED: {target} — added mapping entries (flexible match)")


for patch in PATCHES:
    apply_patch(patch)

apply_mapping_entries()

# Verify KSU_VERSION_FULL exists in ksu.h
ksu_h = os.path.join(KSU_DIR, "include/ksu.h")
if os.path.exists(ksu_h):
    with open(ksu_h, "r") as f:
        content = f.read()
    if "KSU_VERSION_FULL" not in content:
        # Add fallback
        fallback = '\n#ifndef KSU_VERSION_FULL\n#define KSU_VERSION_FULL KSU_VERSION_TAG "+dev"\n#endif\n'
        content += fallback
        with open(ksu_h, "w") as f:
            f.write(content)
        print(f"PATCHED: {ksu_h} — added KSU_VERSION_FULL fallback")
    else:
        print(f"OK: {ksu_h} already has KSU_VERSION_FULL")
else:
    # Legacy branch might have ksu.h at a different path
    # Check drivers/kernelsu
    alt = os.path.join(KSU_DIR, "ksu.h")
    if os.path.exists(alt):
        with open(alt, "r") as f:
            content = f.read()
        if "KSU_VERSION_FULL" not in content:
            fallback = '\n#ifndef KSU_VERSION_FULL\n#define KSU_VERSION_FULL KSU_VERSION_TAG "+dev"\n#endif\n'
            content += fallback
            with open(alt, "w") as f:
                f.write(content)
            print(f"PATCHED: {alt} — added KSU_VERSION_FULL fallback")
        else:
            print(f"OK: {alt} already has KSU_VERSION_FULL")
