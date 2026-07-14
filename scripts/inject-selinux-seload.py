#!/usr/bin/env python3
"""
inject-selinux-seload.py - Add SEL_LOAD kprobe hook to re-apply KSU rules
after any SELinux policy reload.

When init (or any process) writes a new policy to /sys/fs/selinux/load,
the kernel function sel_write_load is called. A kprobe on this function
detects the write and schedules a deferred work that re-applies
apply_kernelsu_rules() + cache_sid() + setup_ksu_cred().

This is the third layer of defense:
  Layer 1: late_initcall (guaranteed boot-time call)
  Layer 2: on_post_fs_data (init.rc triggered)
  Layer 3: sel_write_load kprobe (any policy reload)

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

    # Check if already applied
    if 'sel_write_load_kp' in content:
        print(f"  SEL_LOAD kprobe already present, skipping")
        return True

    # Add includes if not present
    includes_needed = {
        '<linux/kprobes.h>': '#include <linux/kprobes.h>',
        '<linux/workqueue.h>': '#include <linux/workqueue.h>',
    }
    lines = content.split('\n')
    for include_marker, include_line in includes_needed.items():
        if include_marker not in content:
            # Find last #include and insert after
            last_include = -1
            for i, line in enumerate(lines):
                if line.startswith('#include'):
                    last_include = i
            if last_include >= 0:
                lines.insert(last_include + 1, include_line)
                print(f"  Added {include_line}")
            else:
                lines.insert(0, include_line)

    content = '\n'.join(lines)

    # Append kprobe + workqueue code at end of file
    kprobe_code = '''

/* ===== SEL_LOAD kprobe — re-apply KSU rules after policy reload ===== */
#ifdef CONFIG_KPROBES
#include <linux/kprobes.h>
#include <linux/workqueue.h>

static void ksu_sel_write_load_workfn(struct work_struct *work);
static DECLARE_WORK(ksu_sel_write_load_work, ksu_sel_write_load_workfn);

static void ksu_sel_write_load_workfn(struct work_struct *work)
{
	apply_kernelsu_rules();
	cache_sid();
	setup_ksu_cred();
}

static int ksu_sel_write_load_pre(struct kprobe *p, struct pt_regs *regs)
{
	schedule_work(&ksu_sel_write_load_work);
	return 0;
}

static struct kprobe ksu_sel_write_load_kp = {
	.symbol_name = "sel_write_load",
	.pre_handler = ksu_sel_write_load_pre,
};

static int __init ksu_sel_write_load_init(void)
{
	int ret = register_kprobe(&ksu_sel_write_load_kp);
	if (ret)
		pr_warn("ksu: sel_write_load kprobe failed: %d\\n", ret);
	else
		pr_info("ksu: sel_write_load kprobe registered\\n");
	return 0;
}
late_initcall(ksu_sel_write_load_init);
#endif /* CONFIG_KPROBES */
'''

    content = content.rstrip()

    # Only add the work declaration + workfn to boot_event.c
    # (the DECLARE_WORK must live in a compiled .o)
    # The kprobe registration late_initcall goes to core/init.c
    boot_code_only = '''

/* ===== SEL_LOAD kprobe — re-apply KSU rules after policy reload ===== */
#ifdef CONFIG_KPROBES
#include <linux/workqueue.h>

static void ksu_sel_write_load_workfn(struct work_struct *work);
static DECLARE_WORK(ksu_sel_write_load_work, ksu_sel_write_load_workfn);

static void ksu_sel_write_load_workfn(struct work_struct *work)
{
	apply_kernelsu_rules();
	cache_sid();
	setup_ksu_cred();
}
#endif /* CONFIG_KPROBES */
'''
    content += boot_code_only

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added SEL_LOAD workqueue")

    # kprobe registration + late_initcall goes to core/init.c
    init_path = find_file(kernel_root, [
        "drivers/kernelsu/core/init.c",
        "KernelSU/kernel/core/init.c",
    ])
    if not init_path:
        print(f"  WARNING: core/init.c not found, kprobe registration skipped")
        return True

    with open(init_path) as f:
        init_content = f.read()

    if 'ksu_sel_write_load_kp' in init_content:
        print(f"  {init_path}: SEL_LOAD kprobe already present")
        return True

    # Add extern declaration and kprobe init to core/init.c
    kprobe_init = '''

/* ===== SEL_LOAD kprobe (declared in boot_event.c) ===== */
#ifdef CONFIG_KPROBES
#include <linux/kprobes.h>
extern struct kprobe ksu_sel_write_load_kp;
extern struct work_struct ksu_sel_write_load_work;
extern void ksu_sel_write_load_workfn(struct work_struct *work);

static int __init ksu_sel_write_load_init(void)
{
	int ret = register_kprobe(&ksu_sel_write_load_kp);
	if (ret)
		pr_warn("ksu: sel_write_load kprobe failed: %d\\n", ret);
	else
		pr_info("ksu: sel_write_load kprobe registered\\n");
	return 0;
}
late_initcall(ksu_sel_write_load_init);
#endif
'''

    init_content = init_content.rstrip() + kprobe_init
    with open(init_path, 'w') as f:
        f.write(init_content)
    print(f"  {init_path}: added SEL_LOAD kprobe registration late_initcall")
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
