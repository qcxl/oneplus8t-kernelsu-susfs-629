#!/usr/bin/env python3
"""
inject-selinux-domain-init.py - Fix SELinux ksu domain init for builtin mode.

On builtin mode (non-LKM), the init second_stage execve hook doesn't fire on
some kernels (e.g. LineageOS 4.19), so apply_kernelsu_rules() is never called.
This means u:r:ksu:s0 never gets created in the SELinux policy, and all file
operations fail under Enforcing mode.

Fix:
  1. Remove u:r:ksu:s0 requirement from post-fs-data exec in KERNEL_SU_RC
     (chicken-and-egg: the context doesn't exist yet when init runs this exec)
  2. Add apply_kernelsu_rules() + cache_sid() + setup_ksu_cred() to
     on_post_fs_data() in boot_event.c so they run reliably at boot.

Files modified:
  drivers/kernelsu/runtime/ksud_integration.c
  drivers/kernelsu/runtime/boot_event.c

Returns 0 on success, 1 on failure.
"""

import sys, os, re


def find_file(kernel_root, candidates):
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            return p
    return None


def fix_ksud_integration(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/ksud_integration.c",
        "KernelSU/kernel/runtime/ksud_integration.c",
    ])
    if not path:
        print(f"  ERROR: ksud_integration.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # Match both tab-indented (official rifsxd repo) and space-indented (qcxl fork)
    # Line format: \t"    exec u:r:" KERNEL_SU_DOMAIN ":s0 root -- " KSUD_PATH " post-fs-data\n"
    # OR:            "    exec u:r:" KERNEL_SU_DOMAIN ":s0 root -- " KSUD_PATH " post-fs-data\n"
    pattern = re.compile(
        r'^([ \t]*)"([ \t]*)exec u:r:"\s*KERNEL_SU_DOMAIN\s*":s0 root -- "\s*KSUD_PATH\s*" post-fs-data\\n"',
        re.MULTILINE
    )
    replacement = r'\1"\2exec root -- " KSUD_PATH " post-fs-data\\n"'

    new_content, count = pattern.subn(replacement, content, count=1)

    if count == 0:
        # Check if already fixed
        if re.search(r'exec root --.*KSUD_PATH.*post-fs-data', content):
            print(f"  Already fixed, skipping")
            return True
        print(f"  ERROR: cannot find post-fs-data exec pattern in {path}")
        # Debug: show the actual line
        for line in content.split('\n'):
            if 'post-fs-data' in line:
                print(f"  Actual line: {repr(line)}")
        return False

    with open(path, 'w') as f:
        f.write(new_content)
    print(f"  {path}: post-fs-data exec context removed")
    return True


def fix_boot_event(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/boot_event.c",
        "KernelSU/kernel/runtime/boot_event.c",
    ])
    if not path:
        print(f"  ERROR: boot_event.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # 1. Add include if not present (official repo already has it)
    include_line = '#include "selinux/selinux.h"'
    if include_line not in content:
        lines = content.split('\n')
        first_include = -1
        for i, line in enumerate(lines):
            if line.startswith('#include'):
                first_include = i
                break
        if first_include >= 0:
            lines.insert(first_include + 1, include_line)
            content = '\n'.join(lines)
            print(f"  {path}: added #include selinux/selinux.h")
        else:
            content = include_line + '\n' + content
            print(f"  {path}: added #include selinux/selinux.h (no prior include)")
    else:
        print(f"  {path}: include already present")

    # Check if already applied
    if 'apply_kernelsu_rules()' in content:
        print(f"  Already applied, skipping")
        return True

    # 2. Add calls before ksu_load_allow_list
    # Match both tab-indented and space-indented
    marker = re.compile(
        r'^([ \t]*)ksu_load_allow_list\(\);',
        re.MULTILINE
    )

    if not marker.search(content):
        print(f"  ERROR: cannot find ksu_load_allow_list() in {path}")
        return False

    # Capture the indentation from the existing marker
    indent = marker.search(content).group(1)
    block = (
        f'{indent}/* Initialize KSU SELinux domain */\n'
        f'{indent}apply_kernelsu_rules();\n'
        f'{indent}cache_sid();\n'
        f'{indent}setup_ksu_cred();\n'
        f'\n'
        f'{indent}ksu_load_allow_list();'
    )

    content, count = marker.subn(block, content, count=1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added apply_kernelsu_rules + cache_sid + setup_ksu_cred")

    # 3. Fix setup_selinux to clear exec_sid (prevents domain transition on exec)
    selinux_path = find_file(kernel_root, [
        "drivers/kernelsu/selinux/selinux.c",
        "KernelSU/kernel/selinux/selinux.c",
    ])
    if selinux_path:
        with open(selinux_path) as f:
            selinux_content = f.read()

        if 'transive_to_domain(domain, cred, true)' in selinux_content:
            print(f"  {selinux_path}: clear_exec_sid already fixed")
        else:
            old = 'transive_to_domain(domain, cred, false)'
            new = 'transive_to_domain(domain, cred, true)'
            if old in selinux_content:
                selinux_content = selinux_content.replace(old, new, 1)
                with open(selinux_path, 'w') as f:
                    f.write(selinux_content)
                print(f"  {selinux_path}: set clear_exec_sid=true (prevents domain exec transition)")
            else:
                print(f"  WARNING: pattern not found in {selinux_path}")
    else:
        print(f"  WARNING: selinux.c not found, clear_exec_sid fix skipped")

    # 4. Add delayed workqueue directly inside kernelsu_init() (NOT via
    #    late_initcall, which doesn't fire for composite objects).
    #    The work fires ~15s after boot, well after init loads the full
    #    SELinux policy.
    init_path = find_file(kernel_root, [
        "drivers/kernelsu/core/init.c",
        "KernelSU/kernel/core/init.c",
    ])
    if not init_path:
        print(f"  WARNING: core/init.c not found, delayed init skipped")
        return True

    with open(init_path) as f:
        init_content = f.read()

    if 'ksu_delayed_selinux_work' in init_content:
        print(f"  {init_path}: delayed init already present")
        return True

    # Ensure selinux/selinux.h is included
    if '#include "selinux/selinux.h"' not in init_content:
        init_content = init_content.replace(
            '#include "klog.h"',
            '#include "klog.h"\n#include "selinux/selinux.h"'
        )

    # 4a. Add #include <linux/workqueue.h> if not present
    if '#include <linux/workqueue.h>' not in init_content:
        init_content = init_content.replace(
            '#include <linux/export.h>',
            '#include <linux/export.h>\n#include <linux/workqueue.h>'
        )

    # 4b. Add DELAYED_WORK declaration and work function BEFORE
    #     MODULE_LICENSE at end of file. NOT using late_initcall -
    #     instead the schedule call is injected into kernelsu_init().
    work_decl = '''

/* 15-second delayed workqueue: apply KSU SELinux rules AFTER the
 * full SELinux policy has been loaded by init userspace. */
static void ksu_delayed_selinux_init(struct work_struct *work)
{
	apply_kernelsu_rules();
	cache_sid();
	setup_ksu_cred();
}
static DECLARE_DELAYED_WORK(ksu_delayed_selinux_work, ksu_delayed_selinux_init);
'''
    init_content = re.sub(r'^(MODULE_LICENSE\()', work_decl + r'\1', init_content, count=1, flags=re.MULTILINE)

    # 4c. Add schedule_delayed_work() call inside kernelsu_init(),
    #     before the final 'return 0;' at the end of the function.
    #     kernelsu_init() is confirmed to fire (dmesg), so this ensures
    #     the work is always scheduled.
    #     Match 'return 0;' at the end of the init function (not module_exit).
    #     kernelsu_init() ends with:
    #       #endif
    #         return 0;
    #       }
    #     The final return 0; before the closing } of kernelsu_init.
    schedule_call = '\tschedule_delayed_work(&ksu_delayed_selinux_work, 15 * HZ);\n'

    # Find the last 'return 0;' before the first '}' that closes kernelsu_init
    lines = init_content.split('\n')
    modified = False
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        # Look for 'return 0;' inside the init function (after module_exit begins,
        # we're too far. Module exit starts with void __exit kernelsu_exit)
        if stripped == 'return 0;':
            # Check if this is in kernelsu_init by looking at surrounding context
            # (not in kernelsu_exit which starts later)
            surround = '\n'.join(lines[max(0,i-3):i+3])
            if 'kernelsu_exit' not in surround:
                lines.insert(i, schedule_call)
                modified = True
                break

    if modified:
        init_content = '\n'.join(lines)
        with open(init_path, 'w') as f:
            f.write(init_content)
        print(f"  {init_path}: added delayed workqueue scheduling in kernelsu_init()")
    else:
        # Fallback: add at end of file close to return
        init_content = init_content.replace(
            '\treturn 0;\n}\n\nvoid __exit kernelsu_exit',
            '\tschedule_delayed_work(&ksu_delayed_selinux_work, 15 * HZ);\n'
            '\treturn 0;\n}\n\nvoid __exit kernelsu_exit',
            1
        )
        with open(init_path, 'w') as f:
            f.write(init_content)
        print(f"  {init_path}: added delayed workqueue scheduling (fallback)")

    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"ERROR: {root} not a directory")
        sys.exit(1)

    print(f"[SELinux domain init inject] target={root}")
    ok = True
    ok &= fix_ksud_integration(root)
    ok &= fix_boot_event(root)
    print(f"  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
