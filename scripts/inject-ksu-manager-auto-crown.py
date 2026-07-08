#!/usr/bin/env python3
"""
Inject auto-crown manager logic into throne_tracker.c.

Inserts a KSU_MANAGER_PACKAGE matching block before the prune_only
check, so that the manager is auto-detected from packages.list data
even on prune_only=true calls (e.g. on_boot_completed).

Usage: python3 inject-ksu-manager-auto-crown.py <kernel_dir>
"""

import sys
import os

def main():
    if len(sys.argv) < 2:
        print("Usage: inject-ksu-manager-auto-crown.py <kernel_dir>")
        sys.exit(1)

    kernel_dir = sys.argv[1]
    filepath = os.path.join(kernel_dir, "drivers/kernelsu/manager/throne_tracker.c")

    if not os.path.exists(filepath):
        print(f"ERROR: {filepath} not found")
        sys.exit(1)

    with open(filepath, 'r') as f:
        content = f.read()

    if "Auto-crown manager by package name" in content:
        print("  Already injected, skipping")
        return

    block = """#ifdef KSU_MANAGER_PACKAGE
\t{
\t\tstruct uid_data *manager_entry = NULL;
\t\tlist_for_each_entry(np, &uid_list, list) {
\t\t\tif (strcmp(np->package, KSU_MANAGER_PACKAGE) == 0) {
\t\t\t\tmanager_entry = np;
\t\t\t\tbreak;
\t\t\t}
\t\t}
\t\tif (manager_entry) {
\t\t\tif (!ksu_is_manager_appid_valid() ||
\t\t\t    ksu_get_manager_appid() != manager_entry->uid) {
\t\t\t\tksu_set_manager_appid(manager_entry->uid);
\t\t\t}
\t\t}
\t}
#endif

"""

    new_content = content.replace("if (prune_only)", block + "if (prune_only)", 1)

    if new_content == content:
        # Try alternate: the legacy branch uses do_track_throne_core()
        # The target might have different formatting
        print("  WARNING: first replace attempt failed, trying fallback patterns...")
        # Try with surrounding context to handle formatting differences
        new_content = content.replace(
            "\tstruct uid_data *n;\n\n\tif (prune_only)",
            "\tstruct uid_data *n;\n\n" + block + "\tif (prune_only)", 1
        )

    if new_content == content:
        print("  ERROR: 'if (prune_only)' not found in throne_tracker.c - injection FAILED")
        # Print the relevant section for debugging
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'prune_only' in line:
                print(f"  Found 'prune_only' at line {i+1}: {repr(line)}")
        sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(new_content)

    print("  Auto-crown manager block injected into throne_tracker.c")

if __name__ == "__main__":
    main()
