#!/usr/bin/env python3
"""
Inject deferred setup_ksu_cred into do_track_throne_core().

The function retries up to 10 times with 100ms delays. Adding
apply_kernelsu_rules() + setup_ksu_cred() here ensures they get
called AFTER the SELinux policy is loaded (typically 2nd or 3rd retry).
A static flag prevents duplicate policy duplication.

Usage: python3 inject-deferred-ksu-cred.py <kernel_dir>
"""

import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: inject-deferred-ksu-cred.py <kernel_dir>")
        sys.exit(1)

    kernel_dir = sys.argv[1]
    filepath = os.path.join(kernel_dir, "drivers/kernelsu/manager/throne_tracker.c")

    if not os.path.exists(filepath):
        print(f"ERROR: {filepath} not found")
        sys.exit(1)

    with open(filepath, 'r') as f:
        content = f.read()

    if "setup_ksu_cred_retry" in content:
        print("  Already injected, skipping")
        return

    # Insert after the is_lock_held() check, before the filp_open
    # Use extern declarations since throne_tracker.c doesn't include selinux.h
    block = "\t/* setup_ksu_cred: retry-safe, called before filp_open */\n"
    block += "\t{\n"
    block += "\t\tstatic bool ksu_cred_ready = false;\n"
    block += "\t\textern void apply_kernelsu_rules();\n"
    block += "\t\textern void setup_ksu_cred();\n"
    block += "\t\tif (!ksu_cred_ready) {\n"
    block += "\t\t\tapply_kernelsu_rules();\n"
    block += "\t\t\tsetup_ksu_cred();\n"
    block += "\t\t\tksu_cred_ready = true;\n"
    block += "\t\t}\n"
    block += "\t}\n"

    anchor = "if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))"
    if anchor not in content:
        print(f"  ERROR: anchor '{anchor}' not found")
        sys.exit(1)

    new_content = content.replace(anchor, anchor + "\n" + block, 1)
    if new_content == content:
        print("  ERROR: replace failed")
        sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(new_content)

    print("  Deferred setup_ksu_cred injected into do_track_throne_core")


if __name__ == "__main__":
    main()
