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

    # Add everything to boot_event.c: the kprobe struct, handler, and work.
    # The kprobe struct must NOT be static (needed by core/init.c extern).
    # The work and workfn must NOT be static (accessed by core/init.c extern).
    # DECLARE_WORK always adds 'static', so we define the work struct manually.
    boot_code = '''

/* ===== SEL_LOAD kprobe — re-apply KSU rules after policy reload ===== */
#ifdef CONFIG_KPROBES
#include <linux/kprobes.h>
#include <linux/workqueue.h>

static void ksu_sel_write_load_workfn(struct work_struct *work)
{
	apply_kernelsu_rules();
	cache_sid();
	setup_ksu_cred();
}

/* non-static: visible to core/init.c's extern declaration */
struct work_struct ksu_sel_write_load_work;
struct work_struct *ksu_sel_write_load_work_p = &ksu_sel_write_load_work;

static int __init ksu_sel_write_load_work_init(void)
{
	INIT_WORK(&ksu_sel_write_load_work, ksu_sel_write_load_workfn);
	return 0;
}
/* module_init level is earlier than late_initcall, so the work is
   initialized before core/init.c's late_initcall tries to schedule it. */
module_init(ksu_sel_write_load_work_init);

/* non-static: visible to core/init.c's extern declaration */
int ksu_sel_write_load_pre(struct kprobe *p, struct pt_regs *regs)
{
	schedule_work(&ksu_sel_write_load_work);
	return 0;
}

/* non-static: visible to core/init.c's extern declaration */
struct kprobe ksu_sel_write_load_kp = {
	.symbol_name = "sel_write_load",
	.pre_handler = ksu_sel_write_load_pre,
};
#endif /* CONFIG_KPROBES */
'''
    content += boot_code

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added SEL_LOAD kprobe struct + pre_handler + work")

    # core/init.c: just register the kprobe via late_initcall.
    # All definitions live in boot_event.c.
    init_path = find_file(kernel_root, [
        "drivers/kernelsu/core/init.c",
        "KernelSU/kernel/core/init.c",
    ])
    if not init_path:
        print(f"  WARNING: core/init.c not found, kprobe registration skipped")
        return True

    with open(init_path) as f:
        init_content = f.read()

    # Check if kprobe exter declarations already present
    if 'extern struct kprobe ksu_sel_write_load_kp' in init_content:
        print(f"  {init_path}: SEL_LOAD kprobe already present")
        return True

    # Also verify delayed work function exists
    has_delayed_func = 'ksu_delayed_selinux_init' in init_content

    # Instead of a separate late_initcall (which fires too early, before
    # the full policy is loaded), register the kprobe inside the delayed
    # workqueue function from inject-selinux-domain-init.py.
    # The delayed work fires ~15s after boot, well after the full policy
    # is loaded.

    # Find the delayed work function and add kprobe registration inside it
    ksu_func_marker = 'ksu_delayed_selinux_init(struct work_struct *work)'
    ksu_func_end = '\tsetup_ksu_cred();'

    if ksu_func_marker in init_content and ksu_func_end in init_content:
        # Find the end of the function and add kprobe reg before the closing brace
        lines = init_content.split('\n')
        for i, line in enumerate(lines):
            if ksu_func_end in line:
                # Insert kprobe registration after setup_ksu_cred, before return
                kprobe_reg_code = [
                    '\t/* Register SEL_LOAD kprobe (catches policy reloads) */',
                    '\tregister_kprobe(&ksu_sel_write_load_kp);',
                ]
                kprobe_reg_code_guarded = [
                    '\t/* Register SEL_LOAD kprobe (catches policy reloads) */',
                    '#ifdef CONFIG_KPROBES',
                    '\tregister_kprobe(&ksu_sel_write_load_kp);',
                    '#else',
                    '\tpr_debug("ksu: kprobes not enabled, SEL_LOAD hook skipped\\n");',
                    '#endif',
                ]
                for j, code in enumerate(kprobe_reg_code_guarded):
                    lines.insert(i + 1 + j, code)
                init_content = '\n'.join(lines)
                break

        # Add extern declarations at the beginning of the file
        # (after the last #include)
        last_include = -1
        lines = init_content.split('\n')
        for i, line in enumerate(lines):
            if line.startswith('#include'):
                last_include = i
        if last_include >= 0:
            extern_block = [
                '',
                '/* SEL_LOAD kprobe extern (definitions in boot_event.c) */',
                '/* Guards omitted: CONFIG_KPROBES=y always set for KSU */',
                '#include <linux/kprobes.h>',
                'extern int ksu_sel_write_load_pre(struct kprobe *, struct pt_regs *);',
                'extern struct kprobe ksu_sel_write_load_kp;',
                '',
            ]
            for j, line in enumerate(extern_block):
                lines.insert(last_include + 1 + j, line)
            init_content = '\n'.join(lines)

        with open(init_path, 'w') as f:
            f.write(init_content)
        print(f"  {init_path}: added SEL_LOAD kprobe to delayed workqueue")
    else:
        # Fallback: add standalone delayed work + kprobe reg
        fallback_code = '''

/* ===== SEL_LOAD kprobe registration (delayed, after full policy loaded) ===== */
#ifdef CONFIG_KPROBES
#include <linux/kprobes.h>
#include <linux/workqueue.h>
extern int ksu_sel_write_load_pre(struct kprobe *, struct pt_regs *);
extern struct kprobe ksu_sel_write_load_kp;

static void ksu_delayed_kprobe_reg(struct work_struct *work)
{
	register_kprobe(&ksu_sel_write_load_kp);
}
static DECLARE_DELAYED_WORK(ksu_delayed_kprobe_work, ksu_delayed_kprobe_reg);
static int __init ksu_kprobe_delayed_init(void)
{
	schedule_delayed_work(&ksu_delayed_kprobe_work, 15 * HZ);
	return 0;
}
late_initcall(ksu_kprobe_delayed_init);
#endif
'''
        init_content = init_content.rstrip() + fallback_code
        with open(init_path, 'w') as f:
            f.write(init_content)
        print(f"  {init_path}: added fallback delayed SEL_LOAD kprobe registration")

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
