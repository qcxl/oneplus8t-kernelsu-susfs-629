#!/usr/bin/env python3
"""
Inject deferred setup_ksu_cred into boot_event.c for built-in kernels.

Built-in kernels never call setup_ksu_cred() because it's only in
the LKM (late-load) path. This means ksu_cred has no proper SELinux
context, causing -EACCES when throne_tracker reads packages.list.

Fix: add apply_kernelsu_rules() + cache_sid() + setup_ksu_cred()
to on_post_fs_data(), which runs AFTER the SELinux policy is loaded.

Usage: python3 inject-deferred-ksu-cred.py <kernel_dir>
"""

import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: inject-deferred-ksu-cred.py <kernel_dir>")
        sys.exit(1)

    kernel_dir = sys.argv[1]
    filepath = os.path.join(kernel_dir, "drivers/kernelsu/runtime/boot_event.c")

    if not os.path.exists(filepath):
        print(f"ERROR: {filepath} not found")
        sys.exit(1)

    with open(filepath, 'r') as f:
        content = f.read()

    if "deferred cred setup for built-in" in content:
        print("  Already injected, skipping")
        return

    # Use real tabs (\\t = actual tab char in Python) for C code
    block = "\t// deferred cred setup for built-in\n"
    block += "\textern void apply_kernelsu_rules();\n"
    block += "\textern void cache_sid();\n"
    block += "\textern void setup_ksu_cred();\n"
    block += "\tapply_kernelsu_rules();\n"
    block += "\tcache_sid();\n"
    block += "\tsetup_ksu_cred();\n"

    if "stop_input_hook();" not in content:
        print("  ERROR: anchor 'stop_input_hook();' not found in boot_event.c")
        print("  Available lines with 'stop':")
        for i, line in enumerate(content.split('\n')):
            if 'stop' in line.lower():
                print(f"    Line {i+1}: {line.strip()[:80]}")
        sys.exit(1)

    new_content = content.replace("stop_input_hook();", "stop_input_hook();\n" + block, 1)

    if new_content == content:
        print("  ERROR: replace failed - content unchanged")
        sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(new_content)

    print("  Deferred setup_ksu_cred injected into boot_event.c on_post_fs_data")


if __name__ == "__main__":
    main()
