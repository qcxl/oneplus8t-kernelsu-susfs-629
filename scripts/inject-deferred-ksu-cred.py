#!/usr/bin/env python3
"""
Inject deferred setup_ksu_cred into init.c for built-in kernels.

init.c already includes "selinux/selinux.h" which declares
apply_kernelsu_rules(), cache_sid(), setup_ksu_cred().
Just need to add the calls in the built-in path.

Usage: python3 inject-deferred-ksu-cred.py <kernel_dir>
"""

import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: inject-deferred-ksu-cred.py <kernel_dir>")
        sys.exit(1)

    kernel_dir = sys.argv[1]
    filepath = os.path.join(kernel_dir, "drivers/kernelsu/core/init.c")

    if not os.path.exists(filepath):
        print(f"ERROR: {filepath} not found")
        sys.exit(1)

    with open(filepath, 'r') as f:
        content = f.read()

    if "built-in: setup_ksu_cred" in content:
        print("  Already injected, skipping")
        return

    # Use real tabs for C code indentation
    block = "\t// built-in: setup_ksu_cred\n"
    block += "\tapply_kernelsu_rules();\n"
    block += "\tcache_sid();\n"
    block += "\tsetup_ksu_cred();\n"

    if "ksu_file_wrapper_init();" not in content:
        print("  ERROR: anchor 'ksu_file_wrapper_init();' not found in init.c")
        sys.exit(1)

    new_content = content.replace("ksu_file_wrapper_init();", "ksu_file_wrapper_init();\n" + block, 1)

    if new_content == content:
        print("  ERROR: replace failed - content unchanged")
        sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(new_content)

    print("  Deferred setup_ksu_cred injected into init.c built-in path")


if __name__ == "__main__":
    main()
