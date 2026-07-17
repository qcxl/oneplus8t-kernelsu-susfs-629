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
                '#include "klog.h" // IWYU pragma: keep\n#include "ksu.h"\n/* Forward decl: disable_seccomp is exported from kernel/seccomp.c */\nextern void disable_seccomp(struct task_struct *tsk);'
            )
            
            # Add function at end of file (before last newline)
            func = '''
int ksu_handle_prctl(int option, unsigned long arg2, unsigned long arg3,
                     unsigned long arg4, unsigned long arg5)
{
    /* Handle PR_SET_SECCOMP (22): skip seccomp filter installation for the
     * KSU manager app and its children. libc uses prctl(PR_SET_SECCOMP, ...)
     * to install seccomp. Skipping it allows __NR_reboot to work. */
    if (option == 22) {
        uid_t uid = current_uid().val % KSU_PER_USER_RANGE;
        if (ksu_get_manager_appid() == uid && uid >= 10000) {
            printk(KERN_INFO "ksu_prctl: skip PR_SET_SECCOMP pid=%d uid=%d\\n",
                   current->pid, uid);
            return 1;
        }
        return 0;
    }

    if (option != KSU_INSTALL_MAGIC1)
        return 0;

    if (arg2 == KSU_INSTALL_MAGIC2) {
        int fd = ksu_install_fd();
        printk(KERN_INFO "ksu_prctl: INSTALL_MAGIC2 pid=%d fd=%d seccomp_before=%d\\n",
               current->pid, fd, current->seccomp.mode);
        if (fd >= 0) {
            if (copy_to_user((int __user *)arg3, &fd, sizeof(fd)))
                printk(KERN_INFO "ksu_prctl: copy_to_user failed\\n");
            else
                printk(KERN_INFO "ksu_prctl: fd=%d installed for pid=%d\\n", fd, current->pid);
            /* Disable seccomp for ALL threads in this process group.
             * libkernelsu.so may call prctl from a temporary thread that exits,
             * leaving the main thread with Seccomp=2. Children forked from the
             * main thread inherit Seccomp=2, causing SIGSYS on __NR_reboot. */
            {
                struct task_struct *leader = current->group_leader;
                struct task_struct *t = leader;
                int disabled = 0;
                do {
                    if (t->seccomp.mode != 0) {
                        disable_seccomp(t);
                        disabled++;
                    }
                    t = next_thread(t);
                } while (t != leader);
                printk(KERN_INFO "ksu_prctl: seccomp disabled for %d threads\\n",
                       disabled);
            }
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
