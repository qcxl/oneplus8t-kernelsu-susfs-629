#!/usr/bin/env python3
"""
Inject ksu_handle_prctl handler into KSU supercall.c and supercall.h.
This avoids patch context-matching issues with the symlink-based KSU source.

Usage: python3 inject-ksu-prctl.py <kernel_dir>
"""

import sys, os

def main():
    if len(sys.argv) < 2:
        print("Usage: inject-ksu-prctl.py <kernel_dir>")
        sys.exit(1)

    kernel_dir = sys.argv[1]
    
    # Inject into supercall.c
    c_path = os.path.join(kernel_dir, "drivers/kernelsu/supercall/supercall.c")
    h_path = os.path.join(kernel_dir, "drivers/kernelsu/supercall/supercall.h")
    
    # Inject .c file: add #include and function
    success = False
    if os.path.exists(c_path):
        with open(c_path, 'r') as f:
            content = f.read()
        
        if 'ksu_handle_prctl' not in content:
            # Add #include "ksu.h" after the klog.h line
            content = content.replace(
                '#include "klog.h" // IWYU pragma: keep',
                '#include "klog.h" // IWYU pragma: keep\n#include "ksu.h"\n#include <linux/sched/signal.h>\n#include <linux/bitops.h>\n#include <linux/filter.h>\n#include <linux/uaccess.h>'
            )

            # Fix CPU spinning: add .poll handler to anon_ksu_fops so epoll blocks.
            # Without .poll, default returns POLLIN|POLLOUT → libksud epoll_wait
            # returns immediately → 100% CPU spinning. With .poll that returns 0
            # and waits on ksu_poll_wq, epoll blocks forever (correct behavior).
            poll_decl = (
                '\nstatic DECLARE_WAIT_QUEUE_HEAD(ksu_poll_wq);\n'
                'static unsigned int ksu_poll(struct file *filp, poll_table *wait)\n'
                '{\n'
                '\tpoll_wait(filp, &ksu_poll_wq, wait);\n'
                '\treturn 0;\n'
                '}\n'
            )
            content = content.replace(
                'static const struct file_operations anon_ksu_fops',
                poll_decl + 'static const struct file_operations anon_ksu_fops'
            )
            content = content.replace(
                '.release = anon_ksu_release,',
                '.poll = ksu_poll,\n\t.release = anon_ksu_release,'
            )
            
            # Add function at end of file (before last newline)
            func = '''
/* Seccomp bypass bitmap. Tracks UIDs that should skip prctl_set_seccomp.
 * 1024 words * 64 bits = covers UIDs 0-65535 (all Android app UIDs).
 * Populated by:
 *   1. Package-name scan in delayed workqueue (init.c)
 *   2. ksu_handle_prctl(INSTALL_MAGIC2)
 *   3. ksu_handle_sys_reboot(KSU_INSTALL_MAGIC2) */
#define KSU_CMP_WORDS 1024
#define KSU_BMP_MAX_UID (KSU_CMP_WORDS * BITS_PER_LONG)
unsigned long ksu_seccomp_bmp[KSU_CMP_WORDS] = { };

/* Per-UID PID tracking: kill old libksud instances on reconnect.
 * Prevents orphaned daemon processes from spinning at 100% CPU.
 * Array size = 256 (covers UIDs 10000-65535 at KSU_PER_USER_RANGE). */
#define KSU_PID_MAP_SIZE 256
static pid_t ksu_active_pid[KSU_PID_MAP_SIZE] = { };
static DEFINE_SPINLOCK(ksu_pid_lock);

static void ksu_kill_old_instance(uid_t uid)
{
	unsigned int slot = uid % KSU_PID_MAP_SIZE;
	pid_t old_pid;
	struct task_struct *t;

	spin_lock(&ksu_pid_lock);
	old_pid = ksu_active_pid[slot];
	ksu_active_pid[slot] = task_pid_vnr(current);
	if (old_pid && old_pid != task_pid_vnr(current)) {
		t = find_task_by_vpid(old_pid);
		if (t && t->exit_state == 0) {
			printk(KERN_INFO "ksu_prctl: kill old pid=%d uid=%d\\n",
			       old_pid, uid);
			send_sig(SIGKILL, t, 0);
		}
	}
	spin_unlock(&ksu_pid_lock);
}

/* Helper: check if uid is in the seccomp bypass bitmap.
 * Used by kprobe handler (inject-selinux-domain-init.py). */
int ksu_seccomp_check(unsigned int uid)
{
	if (uid < KSU_BMP_MAX_UID)
		return test_bit((int)uid, ksu_seccomp_bmp) ? 1 : 0;
	return 0;
}

int ksu_handle_prctl(int option, unsigned long arg2, unsigned long arg3,
                     unsigned long arg4, unsigned long arg5)
{
    if (option != KSU_INSTALL_MAGIC1)
        return 0;

    if (arg2 == KSU_INSTALL_MAGIC2) {
        /* Kill old libksud instance for this UID before installing new fd.
         * Prevents orphaned daemon processes from accumulating at 100% CPU. */
        {
            uid_t uid = current_uid().val % KSU_PER_USER_RANGE;
            ksu_kill_old_instance(uid);
        }
        int fd = ksu_install_fd();
        printk(KERN_INFO "ksu_prctl: INSTALL_MAGIC2 pid=%d fd=%d seccomp_before=%d\\n",
               current->pid, fd, current->seccomp.mode);
        if (fd >= 0) {
            if (copy_to_user((int __user *)arg3, &fd, sizeof(fd))) {
                printk(KERN_INFO "ksu_prctl: copy_to_user failed, closing fd=%d\\n", fd);
                ksys_close(fd);
                return 1;
            }
                printk(KERN_INFO "ksu_prctl: fd=%d installed for pid=%d\\n", fd, current->pid);
            /* Set PDEATHSIG so this process (libksud daemon) dies when
             * its parent (main app) is killed. Without this, killed apps
             * leave orphan libksud processes spinning at 100% CPU. */
            current->pdeath_signal = SIGKILL;
            /* NOTE: disable_seccomp deliberately REMOVED. */
            /* Register as manager if none exists yet.
             * This MUST happen here (in INSTALL_MAGIC2) because PR_SET_SECCOMP
             * checks ksu_get_manager_appid() and may be called BEFORE the
             * do_get_info auto-registration runs. Without this, child processes
             * would have Seccomp=2 (manager_appid=-1 → no match → seccomp installed). */
            if (!ksu_is_manager_appid_valid()) {
                uid_t mgr_uid = current_uid().val % KSU_PER_USER_RANGE;
                ksu_set_manager_appid(mgr_uid);
                printk(KERN_INFO "ksu_prctl: set manager uid=%d (from INSTALL_MAGIC2)\\n",
                       mgr_uid);
            }
            /* Register this UID in the seccomp bypass bitmap.
              * Kprobe on __secure_computing checks this bitmap. */
            {
                uid_t bmp_uid = current_uid().val % KSU_PER_USER_RANGE;
                if (bmp_uid < KSU_BMP_MAX_UID) {
                    set_bit((int)bmp_uid, ksu_seccomp_bmp);
                    printk(KERN_INFO "ksu_prctl: seccomp_bypass uid=%d\\n", bmp_uid);
                }
            }
            /* Install seccomp filter if not already enabled.
             * On LineageOS 20 userdebug, Bionic skips prctl(PR_SET_SECCOMP)
             * for regular app UIDs (NoNewPrivs=0, no CAP_SYS_ADMIN).
             * prctl(PR_GET_SECCOMP) returns 0 → KSU-Next shows "已禁用".
             * Fix: set no_new_privs + install allow-all filter from kernel. */
            if (current->seccomp.mode == 0) {
                struct sock_fprog fprog;
                struct sock_filter bpf_filter[1];
                mm_segment_t old_fs;
                task_set_no_new_privs(current);
                bpf_filter[0] = BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW);
                fprog.len = 1;
                fprog.filter = bpf_filter;
                old_fs = get_fs();
                set_fs(KERNEL_DS);
                prctl_set_seccomp(SECCOMP_MODE_FILTER, (char __user *)&fprog);
                set_fs(old_fs);
                printk(KERN_INFO "ksu_prctl: seccomp installed mode=%d\\n",
                       current->seccomp.mode);
            }
        }
        return 1;
    }

    if (arg2 == 2) {
        uid_t uid = current_uid().val % KSU_PER_USER_RANGE;
        printk(KERN_INFO "ksu_prctl: get_info pid=%d uid=%d mgr=%d\\n",
               current->pid, uid, ksu_get_manager_appid());
        if (ksu_get_manager_appid() != uid) {
            ksu_set_manager_appid(uid);
        }

        u32 __user *version_ptr = (u32 __user *)arg3;
        u32 __user *flags_ptr = (u32 __user *)arg4;
        u32 version = KERNEL_SU_VERSION;
        u32 flags = 0;

        if (ksu_is_manager_appid_valid())
            flags |= KSU_GET_INFO_FLAG_MANAGER;

        copy_to_user(version_ptr, &version, sizeof(version));
        copy_to_user(flags_ptr, &flags, sizeof(flags));
        printk(KERN_INFO "ksu_prctl: get_info done flags=0x%x\\n", flags);
        return 1;
    }

    printk(KERN_INFO "ksu_prctl: unknown arg2=%lu pid=%d\\n", arg2, current->pid);
    return 0;
}
EXPORT_SYMBOL(ksu_handle_prctl);
'''
            content = content.rstrip() + '\n' + func
            
            with open(c_path, 'w') as f:
                f.write(content)
            print("  ksu_handle_prctl injected into supercall.c")
            # Also modify ksu_handle_sys_reboot in supercall.c to set bitmap bit
            # when fd is installed via reboot syscall path.
            content = open(c_path).read()
            sys_old = ('\tif (magic1 == KSU_INSTALL_MAGIC1 && magic2 == KSU_INSTALL_MAGIC2) {\n'
                      '\t\tint fd = ksu_install_fd();\n'
                      '\t\tif (fd >= 0) {\n'
                      '\t\t\tif (copy_to_user')
            sys_new = ('\tif (magic1 == KSU_INSTALL_MAGIC1 && magic2 == KSU_INSTALL_MAGIC2) {\n'
                      '\t\tint fd = ksu_install_fd();\n'
                      '\t\tif (fd >= 0) {\n'
                      '\t\t\tunsigned int bmp_uid = current_uid().val % KSU_PER_USER_RANGE;\n'
                      '\t\t\tif (bmp_uid < KSU_BMP_MAX_UID)\n'
                      '\t\t\t\tset_bit((int)bmp_uid, ksu_seccomp_bmp);\n'
                      '\t\t\tif (copy_to_user')
            if sys_old in content:
                content = content.replace(sys_old, sys_new, 1)
                open(c_path, 'w').write(content)
                print("  ksu_handle_sys_reboot: set_bit added")
            else:
                print("  WARNING: ksu_handle_sys_reboot pattern not found")
            success = True
        else:
            print("  ksu_handle_prctl already in supercall.c, skipping")
            success = True
    else:
        print(f"  ERROR: {c_path} not found")
        sys.exit(1)
    
    # Inject .h file: add declaration
    if os.path.exists(h_path):
        with open(h_path, 'r') as f:
            content = f.read()
        
        if 'ksu_handle_prctl' not in content:
            decl = '\n// Handle prctl(0xDEADBEEF, ...) for Manager App KSU fd\n'
            decl += 'int ksu_handle_prctl(int option, unsigned long arg2, unsigned long arg3,\n'
            decl += '                     unsigned long arg4, unsigned long arg5);\n'
            
            # Insert after ksu_install_fd declaration
            content = content.replace(
                'int ksu_install_fd(void);\n',
                'int ksu_install_fd(void);\n' + decl
            )
            
            with open(h_path, 'w') as f:
                f.write(content)
            print("  ksu_handle_prctl declaration injected into supercall.h")
        else:
            print("  ksu_handle_prctl already in supercall.h, skipping")
    
    # Also inject auto-registration into dispatch.c do_get_info
    d_path = os.path.join(kernel_dir, "drivers/kernelsu/supercall/dispatch.c")
    if os.path.exists(d_path):
        with open(d_path, 'r') as f:
            content = f.read()
        
        marker = '    if (is_manager()) {\n        cmd.flags |= KSU_GET_INFO_FLAG_MANAGER;'
        auto_reg = """
    /* Register/update caller as manager (handles reinstall with new UID) */
    if (ksu_get_manager_appid() != current_uid().val % KSU_PER_USER_RANGE) {
        ksu_set_manager_appid(current_uid().val % KSU_PER_USER_RANGE);
    }
    if (is_manager()) {
        cmd.flags |= KSU_GET_INFO_FLAG_MANAGER;"""
        
        if 'auto-register caller as manager' not in content:
            if marker in content:
                content = content.replace(marker, auto_reg, 1)
                with open(d_path, 'w') as f:
                    f.write(content)
                print("  do_get_info auto-registration injected into dispatch.c")
            else:
                print("  [WARN] do_get_info marker not found in dispatch.c")
        else:
            print("  do_get_info auto-registration already in dispatch.c, skipping")
    
    if success:
        print("\n=== Verification ===")
        print(f"  supercall.c: {'OK' if os.path.exists(c_path) and 'ksu_handle_prctl' in open(c_path).read() else 'MISSING!'}")
        print(f"  supercall.h: {'OK' if os.path.exists(h_path) and 'ksu_handle_prctl' in open(h_path).read() else 'MISSING!'}")
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
