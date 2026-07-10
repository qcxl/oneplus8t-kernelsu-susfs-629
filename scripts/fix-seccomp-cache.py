#!/usr/bin/env python3
"""Patch seccomp_cache.c to guard against struct mismatch on < 6.1 kernels.

Two versions exist:
  dev branch:   tabs, no kernel version guard (needs fix)
  legacy branch: 4-space indent, wrapped in #if >= 5.10 ... #endif (already safe)

This script handles both formats idempotently.
"""

import sys, os

KERNEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
TARGET = os.path.join(KERNEL_DIR, "drivers/kernelsu/infra/seccomp_cache.c")

if not os.path.exists(TARGET):
    print(f"File not found: {TARGET}")
    sys.exit(0)

with open(TARGET, "r") as f:
    content = f.read()

# Case 1: legacy branch — already behind #if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)
if "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)" in content:
    print("seccomp_cache.c is already behind a 5.10+ guard — no fix needed")
    sys.exit(0)

# Case 2: already has our 6.1 guard
if "#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)" in content:
    print("seccomp_cache.c already has 6.1 guard — no fix needed")
    sys.exit(0)

# Case 3: dev branch format — needs guard injection
# ksu_seccomp_clear_cache (fallback: try tabs, then spaces)

replacements = [
    # Tab-indented (dev branch)
    (
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
        "}",
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
    ),
]

applied = False
for old, new in replacements:
    if old in content:
        content = content.replace(old, new, 1)
        applied = True
        break

if not applied:
    # Case 4: legacy branch with empty stubs (whole file behind #if)
    if "#if LINUX_VERSION_CODE" in content and "ksu_seccomp_clear_cache" not in content:
        print("seccomp_cache.c has empty function stubs — already safe on 4.19")
        sys.exit(0)
    print("ERROR: cannot match ksu_seccomp_clear_cache function body")
    print("File contents:")
    print(content)
    sys.exit(1)

# ksu_seccomp_allow_cache
for old, new in replacements:
    old_a = old.replace("clear_bit", "set_bit").replace(
        "ksu_seccomp_clear_cache", "ksu_seccomp_allow_cache"
    )
    new_a = new.replace("clear_bit", "set_bit").replace(
        "ksu_seccomp_clear_cache", "ksu_seccomp_allow_cache"
    )
    if old_a in content:
        content = content.replace(old_a, new_a, 1)
        applied = True
        break

if not applied:
    print("ERROR: cannot match ksu_seccomp_allow_cache function body")
    sys.exit(1)

with open(TARGET, "w") as f:
    f.write(content)

print("Patched seccomp_cache.c with pre-6.1 safety guard")
