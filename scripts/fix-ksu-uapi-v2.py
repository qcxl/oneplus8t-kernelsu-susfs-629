#!/usr/bin/env python3
"""
fix-ksu-uapi-v2.py - Add KERNEL_SU_UAPI_VERSION v2 support to legacy KSU-Next.

The dev-branch KernelSU-Next app/ksud uses KSU_IOCTL_GET_INFO with size (uapi v2),
but legacy kernel only supports the old size-0 IOCTL, causing "UAPI version mismatch"
error. This script adds:
  - KERNEL_SU_UAPI_VERSION = 2 define
  - uapi_version field to ksu_get_info_cmd
  - ksu_get_info_legacy_cmd struct
  - KSU_IOCTL_GET_INFO (typed) + KSU_IOCTL_GET_INFO_LEGACY (size-0)
  - do_get_info_legacy() handler
Modified: drivers/kernelsu/uapi/supercall.h, drivers/kernelsu/supercall/dispatch.c
"""

import sys, os, re

KSU_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

def find_file(root, candidates):
    for c in candidates:
        p = os.path.join(root, c)
        if os.path.exists(p):
            return p
    return None

def fix_supercall_h():
    # After setup.sh: drivers/kernelsu/ -> ../KernelSU-Next/kernel/ (symlink)
    # uapi/ is at KernelSU-Next/uapi/ (repo root, not inside kernel/)
    # Check via symlink, direct paths, and include/uapi symlink
    path = find_file(KSU_ROOT, [
        "drivers/kernelsu/../uapi/supercall.h",     # via symlink: KernelSU-Next/uapi/supercall.h
        "drivers/kernelsu/include/uapi/supercall.h", # via symlink: .../include/uapi -> ../../uapi/
        "KernelSU-Next/uapi/supercall.h",            # direct path
        "KernelSU/kernel/uapi/supercall.h",          # fallback
    ])
    if not path:
        print("  ERROR: supercall.h not found (checked: drivers/kernelsu/../uapi/, KernelSU-Next/uapi/)")
        return False

    with open(path) as f:
        content = f.read()

    if "KERNEL_SU_UAPI_VERSION" in content:
        print("  supercall.h: UAPI v2 already present")
        return True

    # 1. Add KERNEL_SU_UAPI_VERSION after the app_profile.h include
    content = content.replace(
        '#include "uapi/app_profile.h"',
        '#include "uapi/app_profile.h"\n\n/* UAPI version for user-space compatibility */\n// 2: allowlist v4 root profile flags\nstatic const __u32 KERNEL_SU_UAPI_VERSION = 2;\n'
    )

    # 2. Replace ksu_get_info_cmd to add uapi_version field
    old_cmd = re.search(
        r'struct ksu_get_info_cmd \{[^}]+\};', content, re.DOTALL
    )
    if not old_cmd:
        print("  ERROR: ksu_get_info_cmd struct not found")
        return False

    new_cmd = '''struct ksu_get_info_cmd {
    __u32 version; /* Output: KERNEL_SU_VERSION */
    __u32 flags; /* Output: KSU_GET_INFO_FLAG_* bits */
    __u32 features; /* Output: max feature ID supported */
    __u32 uapi_version; /* Output: KERNEL_SU_UAPI_VERSION */
};

struct ksu_get_info_legacy_cmd {
    __u32 version; /* Output: KERNEL_SU_VERSION */
    __u32 flags; /* Output: KSU_GET_INFO_FLAG_* bits */
    __u32 features; /* Output: max feature ID supported */
    __u32 uapi_version; /* Output: KERNEL_SU_UAPI_VERSION */
};'''
    content = content[:old_cmd.start()] + new_cmd + content[old_cmd.end():]

    # 3. Replace KSU_IOCTL_GET_INFO and add KSU_IOCTL_GET_INFO_LEGACY
    content = content.replace(
        "static const __u32 KSU_IOCTL_GET_INFO = _IOC(_IOC_READ, 'K', 2, 0);",
        "static const __u32 KSU_IOCTL_GET_INFO = _IOR('K', 2, struct ksu_get_info_cmd);\nstatic const __u32 KSU_IOCTL_GET_INFO_LEGACY = _IOC(_IOC_READ, 'K', 2, 0);"
    )

    with open(path, 'w') as f:
        f.write(content)
    print(f"  supercall.h: UAPI v2 added to {path}")
    return True


def fix_dispatch_c():
    dp_path = find_file(KSU_ROOT, [
        "drivers/kernelsu/supercall/dispatch.c",     # via symlink: KernelSU-Next/kernel/supercall/dispatch.c
        "KernelSU-Next/kernel/supercall/dispatch.c", # direct path
        "KernelSU/kernel/supercall/dispatch.c",      # fallback
    ])
    if not dp_path:
        print("  ERROR: dispatch.c not found")
        return False

    with open(dp_path) as f:
        content = f.read()

    if "uapi_version = KERNEL_SU_UAPI_VERSION" in content:
        print("  dispatch.c: UAPI v2 already present")
        return True

    # 1. Add cmd.uapi_version = KERNEL_SU_UAPI_VERSION to do_get_info
    content = content.replace(
        "cmd.features = KSU_FEATURE_MAX;",
        "cmd.features = KSU_FEATURE_MAX;\n\tcmd.uapi_version = KERNEL_SU_UAPI_VERSION;"
    )

    # 2. Add do_get_info_legacy function before the IOCTL handlers mapping
    # NOTE: raw string r'''...''' so that \n in C string literals stays literal
    legacy_fn = r'''

static int do_get_info_legacy(void __user *arg)
{
	struct ksu_get_info_legacy_cmd cmd = {.version = KERNEL_SU_VERSION, .flags = 0};

	if (ksuver_override) {
		cmd.version = ksuver_override;
	}
	
#ifdef MODULE
	cmd.flags |= KSU_GET_INFO_FLAG_LKM;
#endif

	if (is_manager()) {
		cmd.flags |= KSU_GET_INFO_FLAG_MANAGER;
	}
	if (ksu_late_loaded) {
		cmd.flags |= KSU_GET_INFO_FLAG_LATE_LOAD;
	}
	cmd.features = KSU_FEATURE_MAX;
	cmd.uapi_version = KERNEL_SU_UAPI_VERSION;

	if (copy_to_user(arg, &cmd, sizeof(cmd))) {
		pr_err("get_version: copy_to_user failed\n");
		return -EFAULT;
	}

	return 0;
}
'''

    # Also add cmd.uapi_version to do_get_info if not present
    content = content.replace(
        "cmd.features = KSU_FEATURE_MAX;",
        "cmd.features = KSU_FEATURE_MAX;\n\tcmd.uapi_version = KERNEL_SU_UAPI_VERSION;"
    )
    marker = '// IOCTL handlers mapping table'
    pos = content.find(marker)
    if pos < 0:
        print("  ERROR: IOCTL handlers marker not found in dispatch.c")
        return False
    content = content[:pos] + legacy_fn + content[pos:]

    # 3. Add table entry for KSU_IOCTL_GET_INFO_LEGACY after GET_INFO entry
    #    Find the closing }, of GET_INFO and insert legacy entry before REPORT_EVENT
    report_event_pat = re.compile(r'},\s*\{\s*\.cmd\s*=\s*KSU_IOCTL_REPORT_EVENT')
    match = report_event_pat.search(content, pos)
    if not match:
        print("  ERROR: GET_INFO table entry end not found (pattern: KSU_IOCTL_REPORT_EVENT)")
        return False
    # Insert right after the }, that closes GET_INFO (skip 2 chars)
    get_info_entry_end = match.start() + 2

    legacy_entry = '''\n\t{
\t\t.cmd = KSU_IOCTL_GET_INFO_LEGACY,
\t\t.name = "GET_INFO_LEGACY",
\t\t.handler = do_get_info_legacy,
\t\t.perm_check = always_allow
\t},
'''
    content = content[:get_info_entry_end] + legacy_entry + content[get_info_entry_end:]

    with open(dp_path, 'w') as f:
        f.write(content)
    print(f"  dispatch.c: UAPI v2 added to {dp_path}")
    return True


def main():
    ok = True
    ok &= fix_supercall_h()
    ok &= fix_dispatch_c()
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
