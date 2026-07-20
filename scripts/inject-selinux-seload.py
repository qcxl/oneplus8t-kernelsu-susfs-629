#!/usr/bin/env python3
"""
inject-selinux-seload.py - Add delayed SEL_LOAD kprobe to boot_event.c.

Self-contained in boot_event.c: kprobe struct, handler, work, and delayed
registration all in one file. No extern declarations, no cross-file deps.

File modified:
  drivers/kernelsu/runtime/boot_event.c
"""

import sys, os, re


def find_file(kernel_root, candidates):
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            return p
    return None


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

    if 'ksu_sel_write_load_kp' in content:
        print(f"  Already applied, skipping")
        return True

    # Add includes (unconditional - CONFIG_KPROBES=y always)
    includes = {
        '<linux/kprobes.h>': '#include <linux/kprobes.h>',
        '<linux/workqueue.h>': '#include <linux/workqueue.h>',
    }
    lines = content.split('\n')
    for marker, include_line in includes.items():
        if marker not in content:
            last_include = -1
            for i, line in enumerate(lines):
                if line.startswith('#include'):
                    last_include = i
            if last_include >= 0:
                lines.insert(last_include + 1, include_line)
            else:
                lines.insert(0, include_line)
    content = '\n'.join(lines)

    # Append self-contained kprobe code (no externs, no cross-file refs)
    code_block = '''

/*
 * SEL_LOAD kprobe — re-apply KSU rules after any SELinux policy reload.
 * Self-contained: everything lives in this file (struct, handler, work, reg).
 * Attached to delayed workqueue so it fires ~15s after boot (after full
 * policy is loaded).
 */

#include <linux/kprobes.h>
#include <linux/workqueue.h>

/* Non-static so symbol is visible to the module linker */
void ksu_sel_write_load_workfn(struct work_struct *work)
{
	apply_kernelsu_rules();
	cache_sid();
	setup_ksu_cred();
}
struct work_struct ksu_sel_write_load_work;

int ksu_sel_write_load_pre(struct kprobe *p, struct pt_regs *regs)
{
	schedule_work(&ksu_sel_write_load_work);
	return 0;
}

struct kprobe ksu_sel_write_load_kp = {
	.symbol_name = "sel_write_load",
	.pre_handler = ksu_sel_write_load_pre,
};

static int __init ksu_sel_write_load_init(void)
{
	INIT_WORK(&ksu_sel_write_load_work, ksu_sel_write_load_workfn);
	register_kprobe(&ksu_sel_write_load_kp);
	return 0;
}

/*
 * module_init is used here so the kprobe is registered at boot time.
 * The kprobe handler is only invoked when sel_write_load is called
 * (policy reload), which typically does NOT happen during boot on
 * LineageOS. When/if it does, the handler re-applies KSU rules.
 * This is a safety net; the primary init happens via on_post_fs_data
 * event (boot_event.c), triggered by ksud from ramdisk (/sbin/ksud).
 *
 * NOTE: In builtin mode (CONFIG_KSU=y), module_init is equivalent to
 * the device_initcall level. The INIT_WORK + register_kprobe calls
 * are safe at this point: kprobes subsystem and workqueues are up.
 */
module_init(ksu_sel_write_load_init);
'''

    content = content.rstrip() + code_block

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added SEL_LOAD kprobe (self-contained)")
    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"ERROR: {root} not a directory")
        sys.exit(1)

    print(f"[SEL_LOAD kprobe inject] target={root}")
    ok = fix_boot_event(root)
    print(f"  Result: {'ALL OK' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
