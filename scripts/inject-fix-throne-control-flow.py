#!/usr/bin/env python3
"""
inject-fix-throne-control-flow.py — Fix do_track_throne_core() control flow
after inject-deferred-ksu-cred.py has corrupted it.

inject-deferred-ksu-cred.py adds a code block AFTER the `if (is_lock_held(...))`
condition but BEFORE the original if body, pushing the original `{ return false; }`
to become an UNCONDITIONAL block that always runs. Result: do_track_throne_core()
always returns false without ever reading packages.list.

This script runs AFTER inject-deferred-ksu-cred.py in the GHA workflow and
replaces the broken code with a clean implementation.

Usage: python3 inject-fix-throne-control-flow.py <kernel_dir>
"""

import sys, os


def main():
    if len(sys.argv) < 2:
        print("Usage: inject-fix-throne-control-flow.py <kernel_dir>")
        sys.exit(1)

    path = os.path.join(sys.argv[1],
                        "drivers/kernelsu/manager/throne_tracker.c")
    if not os.path.exists(path):
        # Try alternate path
        path = os.path.join(sys.argv[1],
                            "KernelSU/kernel/manager/throne_tracker.c")
    if not os.path.exists(path):
        print(f"ERROR: throne_tracker.c not found in {sys.argv[1]}")
        sys.exit(1)

    with open(path) as f:
        content = f.read()

    if '/* throne_control_flow_fixed */' in content:
        print("  Already fixed, skipping")
        return

    # The deferred-cred inject produced this broken pattern:
    #   if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))
    #   /* setup_ksu_cred: retry-safe, called before filp_open */
    #   {
    #       static bool ksu_cred_ready = false;
    #       extern void apply_kernelsu_rules();
    #       extern void setup_ksu_cred();
    #       if (!ksu_cred_ready) {
    #           apply_kernelsu_rules();
    #           setup_ksu_cred();
    #           ksu_cred_ready = true;
    #       }
    #   }
    #    {                          ← orphan! ALWAYS executes
    #        return false;
    #    }
    #
    # Replace with:
    #   if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH)) {
    #       /* throne_control_flow_fixed */
    #       return false;
    #   }

    old = ('if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))\n'
           '\t/* setup_ksu_cred: retry-safe, called before filp_open */\n'
           '\t{\n'
           '\t\tstatic bool ksu_cred_ready = false;\n'
           '\t\textern void apply_kernelsu_rules();\n'
           '\t\textern void setup_ksu_cred();\n'
           '\t\tif (!ksu_cred_ready) {\n'
           '\t\t\tapply_kernelsu_rules();\n'
           '\t\t\tsetup_ksu_cred();\n'
           '\t\t\tksu_cred_ready = true;\n'
           '\t\t}\n'
           '\t}\n'
           ' {\n'
           '\t\treturn false; // The file is blocked by Android, we ask for a retry\n'
           '\t}')

    if old not in content:
        print("  WARNING: deferred-cred broken pattern not found, checking for other variants...")
        # Try variant with different whitespace
        old_v2 = ('if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))\n'
                  '\t/* setup_ksu_cred: retry-safe, called before filp_open */\n'
                  '\t{\n'
                  '\t\tstatic bool ksu_cred_ready = false;\n'
                  '\t\textern void apply_kernelsu_rules();\n'
                  '\t\textern void setup_ksu_cred();\n'
                  '\t\tif (!ksu_cred_ready) {\n'
                  '\t\t\tapply_kernelsu_rules();\n'
                  '\t\t\tsetup_ksu_cred();\n'
                  '\t\t\tksu_cred_ready = true;\n'
                  '\t\t}\n'
                  '\t}\n'
                  '\t{ return false; }')
        if old_v2 in content:
            new = ('if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH)) {\n'
                   '\t\t/* throne_control_flow_fixed */\n'
                   '\t\treturn false;\n'
                   '\t}')
            content = content.replace(old_v2, new, 1)
            with open(path, 'w') as f:
                f.write(content)
            print("  Fixed (v2)")
            return
        else:
            print("  ERROR: could not find the broken pattern in throne_tracker.c")
            # Show what's actually at the start of do_track_throne_core
            idx = content.find('static bool do_track_throne_core')
            if idx >= 0:
                snippet = content[idx:idx + 800]
                print(f"  do_track_throne_core starts at byte {idx}:")
                for i, line in enumerate(snippet.split('\n')[:15], 1):
                    print(f"    {i}: {repr(line)}")
            sys.exit(1)

    new = ('if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH)) {\n'
           '\t\t/* throne_control_flow_fixed */\n'
           '\t\treturn false;\n'
           '\t}')

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print("  Control flow fixed")


if __name__ == '__main__':
    main()
