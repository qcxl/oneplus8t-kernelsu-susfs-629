#!/usr/bin/env python3
"""Patch seccomp_cache.c to guard against struct mismatch on < 6.1 kernels.

KSU's seccomp_cache.c defines its own struct seccomp_filter with a cache
bitmap field that doesn't exist in the kernel's actual struct on kernels
< 6.1. Writing to filter->cache overflows the 24-byte kernel allocation
and corrupts adjacent heap memory, leading to crashes.
"""

import sys
import os

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
TARGET = os.path.join(KERNEL_DIR, "drivers/kernelsu/infra/seccomp_cache.c")

if not os.path.exists(TARGET):
    print(f"File not found: {TARGET}")
    sys.exit(0)

with open(TARGET, "r") as f:
    content = f.read()

# Guard ksu_seccomp_clear_cache
old = (
    "void ksu_seccomp_clear_cache(struct seccomp_filter *filter, int nr)\n"
    "{\n"
    "\tif (!filter) {\n"
    "\t\treturn;\n"
    "\t}\n"
    "\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_NATIVE_NR) {\n"
    "\t\tclear_bit(nr, filter->cache.allow_native);\n"
    "\t}\n"
    "\n"
    "#ifdef SECCOMP_ARCH_COMPAT\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_COMPAT_NR) {\n"
    "\t\tclear_bit(nr, filter->cache.allow_compat);\n"
    "\t}\n"
    "#endif\n"
    "}"
)

new = (
    "void ksu_seccomp_clear_cache(struct seccomp_filter *filter, int nr)\n"
    "{\n"
    "#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)\n"
    "\tif (!filter) {\n"
    "\t\treturn;\n"
    "\t}\n"
    "\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_NATIVE_NR) {\n"
    "\t\tclear_bit(nr, filter->cache.allow_native);\n"
    "\t}\n"
    "\n"
    "#ifdef SECCOMP_ARCH_COMPAT\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_COMPAT_NR) {\n"
    "\t\tclear_bit(nr, filter->cache.allow_compat);\n"
    "\t}\n"
    "#endif\n"
    "#else\n"
    "\t/* pre-6.1: struct seccomp_filter has no cache field */\n"
    "\t(void)filter;\n"
    "\t(void)nr;\n"
    "#endif\n"
    "}"
)

if old not in content:
    print("WARNING: ksu_seccomp_clear_cache pattern not found, file may have changed")
    # fallback: try without the extra newline between if blocks
    old = old.replace("}\n\n", "}\n")
    if old in content:
        new = new.replace("}\n\n", "}\n")
    else:
        print("ERROR: cannot find ksu_seccomp_clear_cache function body")
        sys.exit(1)

content = content.replace(old, new, 1)

# Guard ksu_seccomp_allow_cache
old = (
    "void ksu_seccomp_allow_cache(struct seccomp_filter *filter, int nr)\n"
    "{\n"
    "\tif (!filter) {\n"
    "\t\treturn;\n"
    "\t}\n"
    "\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_NATIVE_NR) {\n"
    "\t\tset_bit(nr, filter->cache.allow_native);\n"
    "\t}\n"
    "\n"
    "#ifdef SECCOMP_ARCH_COMPAT\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_COMPAT_NR) {\n"
    "\t\tset_bit(nr, filter->cache.allow_compat);\n"
    "\t}\n"
    "#endif\n"
    "}"
)

new = (
    "void ksu_seccomp_allow_cache(struct seccomp_filter *filter, int nr)\n"
    "{\n"
    "#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)\n"
    "\tif (!filter) {\n"
    "\t\treturn;\n"
    "\t}\n"
    "\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_NATIVE_NR) {\n"
    "\t\tset_bit(nr, filter->cache.allow_native);\n"
    "\t}\n"
    "\n"
    "#ifdef SECCOMP_ARCH_COMPAT\n"
    "\tif (nr >= 0 && nr < SECCOMP_ARCH_COMPAT_NR) {\n"
    "\t\tset_bit(nr, filter->cache.allow_compat);\n"
    "\t}\n"
    "#endif\n"
    "#else\n"
    "\t/* pre-6.1: struct seccomp_filter has no cache field */\n"
    "\t(void)filter;\n"
    "\t(void)nr;\n"
    "#endif\n"
    "}"
)

if old not in content:
    print("WARNING: ksu_seccomp_allow_cache pattern not found, file may have changed")
    old = old.replace("}\n\n", "}\n")
    if old in content:
        new = new.replace("}\n\n", "}\n")
    else:
        print("ERROR: cannot find ksu_seccomp_allow_cache function body")
        sys.exit(1)

content = content.replace(old, new, 1)

with open(TARGET, "w") as f:
    f.write(content)

print("Patched seccomp_cache.c with pre-6.1 safety guard")
