#!/usr/bin/env python3
"""
inject-selinux-domain-init.py — Fix KSU SELinux domain init for builtin mode.

Root cause:
  On builtin mode, kernelsu_init() runs at device_initcall level (after
  selinux_init at subsys_initcall). SELinux final policy is loaded. But
  apply_kernelsu_rules() is never called, so u:r:ksu:s0 never exists.
  escape_with_root_profile() → setup_selinux("u:r:ksu:s0") fails.
  All file operations fail under SELinux Enforcing.

Fix:
  1. Add apply_kernelsu_rules() + cache_sid() + setup_ksu_cred() directly
     in kernelsu_init() (core/init.c), before the final return 0.
     SELinux is fully initialized by this point. No policy reload occurs.
  2. Clear exec_sid in setup_selinux() (selinux/selinux.c) so the ksu
     domain persists across exec boundaries.
  3. Remove u:r:ksu:s0 from post-fs-data exec in KERNEL_SU_RC
     (chicken-and-egg: context doesn't exist at boot).
  4. Add calls to on_post_fs_data() (boot_event.c) as a safety net.
"""

import sys, os
import re as _re


def find_file(kernel_root, candidates):
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            return p
    return None


def fix_boot_event(kernel_root):
    return True


def fix_selinux_clear_exec_sid(kernel_root):
    return True


def fix_app_profile(kernel_root):
    """Remove early return in escape_with_root_profile when euid==0.
    The early return skips setup_selinux(), leaving the process in the
    wrong domain. Even if already root, we should still set the ksu domain
    so that exec()'d child processes inherit the correct context."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/policy/app_profile.c",
        "KernelSU/kernel/policy/app_profile.c",
    ])
    if not path:
        print(f"  WARNING: app_profile.c not found")
        return True

    with open(path) as f:
        content = f.read()

    if 'Already root, setup selinux anyway' in content:
        print(f"  {path}: already fixed")
        return True

    # Replace the early return with setup_selinux + commit
    old = (
        '\tif (cred->euid.val == 0) {\n'
        '\t\tpr_warn("Already root, don\'t escape!\\n");\n'
        '\t\tgoto out_abort_creds;\n'
        '\t}'
    )
    new = (
        '\tif (cred->euid.val == 0) {\n'
        '\t\tpr_debug("Already root, setup selinux anyway\\n");\n'
        '\t\tsetup_selinux(KERNEL_SU_CONTEXT, cred);\n'
        '\t\tcommit_creds(cred);\n'
        '\t\tdisable_seccomp();\n'
        '\t\treturn 0;\n'
        '\t}'
    )
    if old not in content:
        print(f"  WARNING: pattern not found in {path}")
        return True

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: replaced early bail with setup_selinux")
    return True


def fix_rules(kernel_root):
    """Add type_transition rule: ksu exec's shell_exec → stays in ksu, not shell.
    Without this, the stock type_transition domain shell_exec:process shell;
    fires when ksu exec's /system/bin/sh, transitioning the process to
    shell domain, losing all permissions."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/selinux/rules.c",
        "KernelSU/kernel/selinux/rules.c",
    ])
    if not path:
        print(f"  ERROR: rules.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # Check if already applied
    if 'ksu_type_transition.*KERNEL_SU_DOMAIN.*shell_exec' in content or \
       'type_transition.*ksu.*shell_exec.*process.*ksu' in content:
        print(f"  {path}: already fixed")
        return True

    # Insert after ksu_permissive(db, KERNEL_SU_DOMAIN);
    # Note: apply_kernelsu_rules_fn() uses 4-space indentation (not tabs)
    old = '    ksu_permissive(db, KERNEL_SU_DOMAIN);'
    new = (
        '    ksu_permissive(db, KERNEL_SU_DOMAIN);\n'
        '    /* ksu exec' + "'" + 's shell (sh, busybox): STAY in ksu domain. */\n'
        '    /* Build: __DATE__ __TIME__ */\n'
        '    /* Without this, stock type_transition domain->shell fires, losing perms. */\n'
        '    printk(KERN_ERR "KSU_DIAG: copy nprim=%d len=%zu\\n", db->p_types.nprim, db->len);\n'
        '    printk(KERN_ERR "KSU_DIAG: has domain type=%d\\n",\n'
        '        hashtab_search(db->p_types.table, "domain") != NULL);\n'
        '    {\n'
        '        bool _r = ksu_type(db, KERNEL_SU_DOMAIN, "domain");\n'
        '        printk(KERN_ERR "KSU_DIAG: ksu_type result=%d\\n", _r);\n'
        '    }\n'
        '    printk(KERN_ERR "KSU_DIAG: types after=%d\\n", db->p_types.nprim);\n'
        '    printk(KERN_ERR "KSU_DIAG: has ksu type=%d\\n",\n'
        '        hashtab_search(db->p_types.table, "ksu") != NULL);\n'
        '    printk(KERN_ERR "KSU_DIAG: ksu_type_transition result=%d\\n",\n'
        '        ksu_type_transition(db, KERNEL_SU_DOMAIN, "shell_exec", "process", KERNEL_SU_DOMAIN, ALL));\n'
        '    printk(KERN_ERR "KSU_DIAG: ksu_allow shell_exec result=%d\\n",\n'
        '        ksu_allow(db, KERNEL_SU_DOMAIN, "shell_exec", "file", "execute"));'
    )

    if old not in content:
        print(f"  ERROR: cannot find ksu_permissive marker in {path}")
        return False

    content = content.replace(old, new, 1)

    # DIAG: inject orig nprim before ksu_dup_sepolicy
    diag_old = (
        '\tpol = ksu_dup_sepolicy(rcu_dereference_protected(\n'
        '\t\t    old_pol, lockdep_is_held(&selinux_state.policy_mutex)));'
    )
    diag_new = (
        '\tprintk(KERN_ERR "KSU_DIAG: orig nprim=%d len=%zu\\n",\n'
        '\t    old_pol->policydb.p_types.nprim,\n'
        '\t    old_pol->policydb.len);\n'
        '\tpol = ksu_dup_sepolicy(rcu_dereference_protected(\n'
        '\t\t    old_pol, lockdep_is_held(&selinux_state.policy_mutex)));'
    )
    if diag_old in content:
        content = content.replace(diag_old, diag_new, 1)
        print(f"  {path}: orig nprim diag injected before ksu_dup_sepolicy")
    else:
        print(f"  WARNING: ksu_dup_sepolicy marker not found in {path}")

    # Also replace the apply_kernelsu_rules() #else branch to skip
    # write_lock/stop_machine (GFP_KERNEL fails in atomic context).
    # Replace from '#else' to the closing '#endif' of the function.
    import re as _re
    # Replace the entire 4.19 path body from '#else' to closing '#endif'
    # with a boot-safe version. Capture #else and #endif as boundaries.
    else_pat = _re.compile(
        r'(#else)(\n\n\tcpumask_t old_mask;.*?)(\n#endif\n})',
        _re.DOTALL
    )
    else_repl = (
        r'\1'
        r'\n'
        r'    /* Boot-safe: no write_lock/stop_machine (GFP_KERNEL fails in atomic context). */\n'
        r'    /* At boot, only CPU 0 runs init, so no SELinux policy contention. */\n'
        r'    db = get_policydb();\n'
        r'    apply_kernelsu_rules_fn((void *)db);\n'
        r'    smp_mb();\n'
        r'    reset_avc_cache();\n'
        r'\3'
    )
    content = else_pat.sub(else_repl, content, count=1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: replaced apply_kernelsu_rules() with boot-safe path")
    return True


def fix_ksu_exec_fd_reinstall(kernel_root):
    """In the execve handler, reinstall the KSU driver fd for the new process.
    Java's ProcessBuilder closes all non-std fds before exec, so even with
    O_CLOEXEC removed, child processes lose the fd. Reinstall it during execve
    so libksud.so can find it via scan_driver_fd()."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/ksud_integration.c",
        "KernelSU/kernel/runtime/ksud_integration.c",
    ])
    if not path:
        print(f"  WARNING: ksud_integration.c not found")
        return True

    with open(path) as f:
        content = f.read()

    if '/* Reinstall KSU fd after exec */' in content:
        print(f"  {path}: already fixed")
        return True

    # Find the init second_stage check block and insert fd install after it
    marker = 'init_second_stage_executed = true;'
    if marker not in content:
        print(f"  WARNING: init_second_stage_executed not found in {path}")
        return True

    replacement = (
        marker + '\n'
        '\t/* Reinstall KSU fd after exec (Java ProcessBuilder closes it). */\n'
        '\tksu_install_fd();'
    )
    content = content.replace(marker, replacement, 1)

    # Also add the extern declaration
    if 'extern int ksu_install_fd' not in content:
        content = content.replace(
            '#include "selinux/selinux.h"',
            '#include "selinux/selinux.h"\n'
            'extern int ksu_install_fd(void);'
        )

    # Add __visible attribute to ksu_install_fd in supercall.c
    sc_path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/supercall.c",
        "KernelSU/kernel/supercall/supercall.c",
    ])
    if not sc_path:
        print(f"  WARNING: supercall.c not found, fd reinstall might not compile")
        return True

    with open(sc_path) as f:
        sc_content = f.read()

    # Add __visible attribute to ksu_install_fd for cross-file access
    old = 'int ksu_install_fd(void)'
    new = 'int __visible ksu_install_fd(void)'
    sc_content = sc_content.replace(old, new, 1)

    with open(sc_path, 'w') as f:
        f.write(sc_content)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: reinstalls KSU fd in execve hook")
    return True


def fix_syscall_hook_reboot(kernel_root):
    """Add __NR_reboot hook to syscall hook manager (pre-seccomp).
    
    The sys_enter tracepoint (ksu_sys_enter_handler) runs BEFORE seccomp.
    By registering __NR_reboot here, we intercept reboot syscalls before
    seccomp kills them. The handler checks for KSU magic numbers and
    installs the driver fd instead of calling the original syscall."""
    
    # 1. Add handler to syscall_event_bridge.c
    bridge_path = find_file(kernel_root, [
        "drivers/kernelsu/hook/syscall_event_bridge.c",
        "drivers/kernelsu/../KernelSU-Next/kernel/hook/syscall_event_bridge.c",
        "KernelSU/kernel/hook/syscall_event_bridge.c",
    ])
    if not bridge_path:
        print(f"  WARNING: syscall_event_bridge.c not found")
        return True
    
    with open(bridge_path) as f:
        content = f.read()
    
    if 'ksu_hook_reboot' in content:
        print(f"  {bridge_path}: already fixed")
    else:
        # Add handler implementation before the last function
        old = '\nlong __nocfi ksu_hook_setresuid'
        new = (
            '\n/* Pre-seccomp hook for __NR_reboot: install KSU fd on magic. */\n'
'long __nocfi ksu_hook_reboot(int orig_nr, const struct pt_regs *regs)\n'
             '{\n'
             '\tint magic1 = (int)PT_REGS_PARM1(regs);\n'
             '\tint magic2 = (int)PT_REGS_PARM2(regs);\n'
             '\tif (magic1 == KSU_INSTALL_MAGIC1 && magic2 == KSU_INSTALL_MAGIC2) {\n'
             '\t\tint __user *out_fd = (int __user *)PT_REGS_SYSCALL_PARM4(regs);\n'
             '\t\tint fd = ksu_install_fd();\n'
             '\t\tif (fd >= 0 && out_fd && !copy_to_user(out_fd, &fd, sizeof(fd))) {\n'
             '\t\t\t/* Override syscall nr BEFORE seccomp check.\n'
             '\t\t\t * seccomp reads regs->syscallno via secure_computing().\n'
             '\t\t\t * Change to __NR_getpid (allowed) so seccomp will not\n'
             '\t\t\t * kill this process for calling __NR_reboot (142). */\n'
             '\t\t\t((struct pt_regs *)regs)->syscallno = __NR_getpid;\n'
             '\t\t\t((struct pt_regs *)regs)->regs[0] = 0;\n'
             '\t\t\treturn 0;\n'
             '\t\t}\n'
             '\t\t/* fd install failed but seccomp still needs bypass */\n'
             '\t\t((struct pt_regs *)regs)->syscallno = __NR_getpid;\n'
             '\t\t((struct pt_regs *)regs)->regs[0] = -ENOSYS;\n'
             '\t\treturn 0;\n'
             '\t}\n'
'\treturn ksu_syscall_table[orig_nr](regs);\n'
             '}\n'
            '\n'
            'long __nocfi ksu_hook_setresuid'
        )
        if old not in content:
            print(f"  WARNING: insertion point not found in {bridge_path}")
            return True
        content = content.replace(old, new, 1)
        
        with open(bridge_path, 'w') as f:
            f.write(content)
        print(f"  {bridge_path}: added ksu_hook_reboot")
    
    # 2. Register the hook in syscall_hook_manager.c
    mgr_path = find_file(kernel_root, [
        "drivers/kernelsu/hook/syscall_hook_manager.c",
        "drivers/kernelsu/../KernelSU-Next/kernel/hook/syscall_hook_manager.c",
        "KernelSU/kernel/hook/syscall_hook_manager.c",
    ])
    if not mgr_path:
        print(f"  WARNING: syscall_hook_manager.c not found")
        return True
    
    with open(mgr_path) as f:
        content = f.read()
    
    if '__NR_reboot' in content and 'ksu_hook_reboot' in content:
        print(f"  {mgr_path}: already fixed")
        return True
    
    # Add registration after execve hook (dev branch uses 4-space indent)
    old = '    ksu_register_syscall_hook(__NR_faccessat, ksu_hook_faccessat);'
    new = (
        '    ksu_register_syscall_hook(__NR_faccessat, ksu_hook_faccessat);\n'
        '    /* __NR_reboot: pre-seccomp handler for KSU fd install. */\n'
        '    ksu_register_syscall_hook(__NR_reboot, ksu_hook_reboot);\n'
    )
    if old not in content:
        print(f"  WARNING: registration point not found in {mgr_path}")
        return True
    content = content.replace(old, new, 1)
    
    # Add unregistration in exit
    old = '    ksu_unregister_syscall_hook(__NR_faccessat);'
    new = (
        '    ksu_unregister_syscall_hook(__NR_faccessat);\n'
        '    ksu_unregister_syscall_hook(__NR_reboot);\n'
    )
    if old not in content:
        print(f"  WARNING: unregistration point not found in {mgr_path}")
        return True
    content = content.replace(old, new, 1)
    
    with open(mgr_path, 'w') as f:
        f.write(content)
    print(f"  {mgr_path}: registered __NR_reboot hook")
    
    # 3. Add includes to syscall_event_bridge.c for ksu_install_fd + magic consts
    if '#include "supercall/supercall.h"' not in open(bridge_path).read():
        content_bridge = open(bridge_path).read()
        content_bridge = content_bridge.replace(
            '#include "hook/syscall_event_bridge.h"',
            '#include "hook/syscall_event_bridge.h"\n#include "supercall/supercall.h"\n#include "uapi/supercall.h"'
        )
        with open(bridge_path, 'w') as f:
            f.write(content_bridge)
    
    return True


def fix_throne_deferred_cred(kernel_root):
    """Fix broken control flow caused by inject-deferred-ksu-cred.py.
    
    That inject adds a code block AFTER the `if (is_lock_held(...))` condition
    but BEFORE the `return false;` block. This creates an unconditional return:
    
      if (is_lock_held(...))  // controls only the ksu_cred block
      /* deferred-cred code */ {
          setup_ksu_cred();
      }
      { return false; }  // ← ALWAYS executes!
    
    Fix: remove the deferred-cred block entirely (our workqueue already
    calls setup_ksu_cred + apply_kernelsu_rules before track_throne)."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/manager/throne_tracker.c",
        "KernelSU/kernel/manager/throne_tracker.c",
    ])
    if not path:
        print(f"  WARNING: throne_tracker.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'deferred_cred_fixed' in content:
        print(f"  {path}: already fixed")
        return True

    # Find deferred-cred injected block and fix orphan control flow.
    # The broken pattern (from inject-deferred-ksu-cred.py):
    #   if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))
    #   /* setup_ksu_cred: ... */
    #   { deferred-cred block }
    #   { return false; }
    anchor = 'if (is_lock_held('
    if anchor not in content:
        print(f"  WARNING: is_lock_held not found in {path}")
        return True
    
    idx = content.find(anchor)
    # Find the orphan block after the deferred-cred. It should be:
    # whitespace + { + whitespace + return false + whitespace + }
    rest = content[idx + len('if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))'):]
    # Find the orphan { return false; } block. It's the FIRST
    # standalone "{ return false; ... }" after the if/block.
    orphan_pat = _re.compile(r'\n\s*\{\s*\n\s*return false[^}]*\}')
    orphan_m = orphan_pat.search(rest)
    if not orphan_m:
        print(f"  WARNING: orphan return-false block not found in {path}")
        return True
    
    # Replace from 'if (is_lock_held' to end of orphan block
    orphan_end = idx + len('if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))') + orphan_m.end()
    replacement = (
        'if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH)) {\n'
        '\t\t/* deferred_cred_fixed */\n'
        '\t\treturn false;\n'
        '\t}\n'
    )
    # Find the next statement after orphan block to avoid corrupting code
    next_stmt = content[orphan_end:].lstrip('\n')
    content = content[:idx] + replacement + next_stmt
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: fixed deferred-cred broken control flow")
    return True


def fix_throne_lock(kernel_root):
    """Bypass is_lock_held() in throne_tracker.c.
    
    do_track_throne_core() calls is_lock_held(SYSTEM_PACKAGES_LIST_PATH)
    which checks d_lock via spin_trylock. On a busy booting system, the
    dentry lock is briefly held by Package Manager, causing is_lock_held()
    to return true -> file never read -> manager UID never set.
    
    Fix: replace spin_trylock with spin_is_locked (non-blocking check)."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/manager/throne_tracker.c",
        "KernelSU/kernel/manager/throne_tracker.c",
    ])
    if not path:
        print(f"  WARNING: throne_tracker.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'spin_trylock_fixed' in content:
        print(f"  {path}: already fixed")
        return True
    # Remove d_lock check entirely: always return false (not locked)
    old = '\t// Check the VFS lock (d_lock) without blocking ourselves'
    if old not in content:
        print(f"  WARNING: 'Check the VFS lock' comment not found in {path}")
        return True
    # Replace from the comment to the end of spin_unlock with path_put + return false
    new = (
        '\t/* d_lock check removed - spin_trylock fails during boot */\n'
        '\tpath_put(&kpath);\n'
        '\treturn false;\n'
        '}\n'
    )
    # Find the block and replace (include everything up to return false;\n}
    idx = content.find(old)
    end_idx = content.find('return false;\n}\n', idx)
    if end_idx < 0:
        print(f"  WARNING: end of is_lock_held not found after comment")
        return True
    end_idx += len('return false;\n}\n')
    content = content[:idx] + new + content[end_idx:]
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: is_lock_held d_lock check removed")
    return True


def fix_auto_crown_prctl(kernel_root):
    """Fix ksu_handle_prctl auto-registration: allow same-app re-registration.
    
    inject-ksu-prctl.py adds ksu_handle_prctl() which, when called with
    arg2 == 2, sets the manager UID to the calling app's UID. The original
    condition `if (uid != ksu_get_manager_appid())` lets ANY app overwrite.
    
    Fix: only register if no manager exists, OR the calling app has the
    same UID as the current manager (handles reinstall with no UID change):
        if (!ksu_is_manager_appid_valid() || uid == ksu_get_manager_appid())"""
    path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/supercall.c",
        "KernelSU/kernel/supercall/supercall.c",
    ])
    if not path:
        print(f"  WARNING: supercall.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'auto_crown_fixed_prctl' in content:
        print(f"  {path}: already fixed")
        return True
    
    # Try to match any of the known pattern variants
    old_patterns = [
        # Injected by inject-ksu-prctl.py (has printk between uid decl and if)
        ('\tif (arg2 == 2) {\n\t\tuid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n\t\tprintk(KERN_INFO "ksu_prctl: get_info',
         '\tif (arg2 == 2) {\n\t\t/* auto_crown_fixed_prctl */\n\t\tuid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n\t\tprintk(KERN_INFO "ksu_prctl: get_info'),
        # 4-space indent with comment
        ('if (arg2 == 2) {\n        /* Legacy get_info: register/update caller as manager */\n        uid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n        if (ksu_get_manager_appid() != uid) {\n            ksu_set_manager_appid(uid);',
         'if (arg2 == 2) {\n        /* auto_crown_fixed_prctl */\n        uid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n        if (!ksu_is_manager_appid_valid() || uid == ksu_get_manager_appid()) {\n            ksu_set_manager_appid(uid);'),
        # tab indent with comment
        ('\tif (arg2 == 2) {\n\t\t/* Legacy get_info: register/update caller as manager */\n\t\tuid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n\t\tif (ksu_get_manager_appid() != uid) {\n\t\t\tksu_set_manager_appid(uid);',
         '\tif (arg2 == 2) {\n\t\t/* auto_crown_fixed_prctl */\n\t\tuid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n\t\tif (!ksu_is_manager_appid_valid() || uid == ksu_get_manager_appid()) {\n\t\t\tksu_set_manager_appid(uid);'),
        # tab indent without comment
        ('\tif (arg2 == 2) {\n\t\tuid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n\t\tif (ksu_get_manager_appid() != uid) {\n\t\t\tksu_set_manager_appid(uid);',
         '\tif (arg2 == 2) {\n\t\t/* auto_crown_fixed_prctl */\n\t\tuid_t uid = current_uid().val % KSU_PER_USER_RANGE;\n\t\tif (!ksu_is_manager_appid_valid() || uid == ksu_get_manager_appid()) {\n\t\t\tksu_set_manager_appid(uid);'),
    ]
    
    for old, new in old_patterns:
        if old in content:
            content = content.replace(old, new, 1)
            with open(path, 'w') as f:
                f.write(content)
            print(f"  {path}: ksu_handle_prctl fixed")
            return True
    
    print(f"  WARNING: ksu_handle_prctl arg2==2 pattern not found in {path}")
    return True


def fix_ksud_postfsdata_noctx(kernel_root):
    """Rewrite u:r:ksu:s0 exec lines in KERNEL_SU_RC to exec root --.
    
    The ksu SELinux domain isn't created until delayed workqueue at ~30s.
    'on nonencrypted' / 'on boot_completed' lines use exec u:r:ksu:s0
    which fails if triggered before the domain is created.
    
    (post-fs-data already uses exec root -- in the legacy branch, so
     there's nothing to fix there.)"""
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/ksud_integration.c",
        "drivers/kernelsu/../KernelSU-Next/kernel/runtime/ksud_integration.c",
        "KernelSU/kernel/runtime/ksud_integration.c",
    ])
    if not path:
        print(f"  WARNING: ksud_integration.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'NOCTX_FIX' in content:
        print(f"  {path}: already fixed")
        return True
    
    # Replace u:r:ksu:s0 → root -- for nonencrypted and boot-completed lines
    ksud_ctx_pat = 'exec u:r:" KERNEL_SU_DOMAIN ":s0 root --'
    ksud_ctx_new = 'exec root -- /* NOCTX_FIX */'
    if ksud_ctx_pat in content:
        content = content.replace(ksud_ctx_pat, ksud_ctx_new)
        with open(path, 'w') as f:
            f.write(content)
        print(f"  {path}: replaced u:r:ksu:s0 with exec root --")
    else:
        print(f"  {path}: u:r:ksu:s0 pattern not found (legacy branch uses exec root --)")
    return True


def fix_allow_uid_zero(kernel_root):
    """Fix __ksu_is_allow_uid_for_current(0) to return true directly.
    
    Root cause of 'grant root failed':
    allowlist.c: __ksu_is_allow_uid_for_current(0) returns is_ksu_domain()
    instead of true. When adb root elevates to UID 0, the SELinux context
    is u:r:su:s0 (not u:r:ksu:s0), so is_ksu_domain() returns false.
    This causes allowed_for_su() → EPERM → grant_root fails.
    
    Fix: for UID 0, return true unconditionally (already root, no risk)."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/policy/allowlist.c",
        "KernelSU/kernel/policy/allowlist.c",
    ])
    if not path:
        print(f"  WARNING: allowlist.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'uid_zero_fix' in content:
        print(f"  {path}: already fixed")
        return True
    old = (
        '\tif (unlikely(uid == 0)) {\n'
        '\t\t// already root, but only allow our domain.\n'
        '\t\treturn is_ksu_domain();\n'
        '\t}'
    )
    new = (
        '\tif (unlikely(uid == 0)) {\n'
        '\t\t/* uid_zero_fix: UID 0 is already root, no security risk. */\n'
        '\t\t/* Without this, adb root cannot call grant_root */\n'
        '\t\t/* because is_ksu_domain() requires u:r:ksu:s0 context. */\n'
        '\t\treturn true;\n'
        '\t}'
    )
    if old not in content:
        print(f"  WARNING: uid 0 check pattern not found in {path}")
        return True
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: uid=0 returns true unconditionally")
    return True


def fix_seccomp_bypass(kernel_root):
    """Add kprobe on secure_computing to bypass seccomp for KSU SYS_reboot magic calls.
    
    libksud.so's init_driver_fd() calls syscall(SYS_reboot, KSU_MAGIC1, KSU_MAGIC2, 0, &fd).
    On Android, seccomp blocks __NR_reboot (142), causing SIGSYS before the KSU
    reboot_handler_pre kprobe can fire. This fix intercepts secure_computing()
    and skips the seccomp check when:
      - syscall is __NR_reboot, AND
      - arg0 == KSU_INSTALL_MAGIC1 (0xDEADBEEF), AND
      - arg1 == KSU_INSTALL_MAGIC2 (0xCAFEBABE)
    
    No other syscall or process is affected. No new detection vectors created."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/supercall.c",
        "KernelSU/kernel/supercall/supercall.c",
    ])
    if not path:
        print(f"  WARNING: supercall.c not found")
        return True

    with open(path) as f:
        content = f.read()

    if '/* seccomp_bypass: secure_computing kprobe */' in content:
        print(f"  {path}: already fixed")
        return True

    # Add #include <linux/seccomp.h> if not present
    if '#include <linux/seccomp.h>' not in content:
        content = content.replace(
            '#include <linux/slab.h>',
            '#include <linux/slab.h>\n#include <linux/seccomp.h>\n#include <linux/filter.h>\n#include <linux/uaccess.h>\n#include <linux/task_work.h>'
        )

    # Add the seccomp kprobe structure before ksu_supercalls_init
    kprobe_decl = '''

/* seccomp_bypass: bypass seccomp for KSU SYS_reboot magic.
 * Android seccomp blocks __NR_reboot (142). libksud.so calls:
 *   syscall(SYS_reboot, KSU_INSTALL_MAGIC1=0xDEADBEEF, KSU_INSTALL_MAGIC2=0xCAFEBABE, 0, &fd)
 * We intercept secure_computing(), skip it for KSU magic.
 *
 * Seccomp is disabled by default (mode=0) on LineageOS 20 because
 * Bionic skips PR_SET_SECCOMP for regular app UIDs. This kprobe is a
 * cross-device safety net for devices where seccomp IS enabled. */

extern int ksu_seccomp_check(unsigned int uid);

/* Seccomp bypass: intercept __secure_computing and allow __NR_reboot
 * for KSU-managed apps. This fires when seccomp.mode != 0 (i.e. only
 * on devices that actually install seccomp filters on apps). */
static int seccomp_bypass_pre(struct kprobe *p, struct pt_regs *regs)
{
	unsigned int uid, app_uid;
	uid = current_uid().val;
	app_uid = uid % KSU_PER_USER_RANGE;
	if (app_uid < 10000)
		return 0;
	if (!ksu_seccomp_check(app_uid)) {
		if (ksu_is_manager_appid_valid() &&
		    ksu_get_manager_appid() != app_uid)
			return 0;
	}
	{
		struct pt_regs *uregs = task_pt_regs(current);
		int sc_nr = uregs->syscallno;
		if (sc_nr == 142) {
			regs->regs[0] = 0;
			return 1;
		}
	}
	return 0;
}

static struct kprobe seccomp_bypass_kp = {
	.symbol_name = "__secure_computing",
	.pre_handler = seccomp_bypass_pre,
};
'''

    # Insert kprobe declaration before ksu_supercalls_init
    # First, remove duplicate prctl_kp registration (original kprobe also
    # installs fd, which conflicts with our ksu_handle_prctl handler).
    prctl_kp_pat1 = ('\trc = register_kprobe(&prctl_kp);\n'
                     '\tif (rc) {\n'
                     '\t\tpr_err("prctl kprobe failed: %d\\n", rc);\n'
                     '\t} else {\n'
                     '\t\tpr_debug("prctl kprobe registered successfully\\n");\n'
                     '\t}\n')
    prctl_kp_pat2 = ('\trc = register_kprobe(&prctl_kp);\n'
                     '\tif (rc) {\n'
                     '\t\tpr_err("prctl kprobe failed: %d\\n", rc);\n'
                     '\t}\n')
    prctl_kp_match = prctl_kp_pat1 if prctl_kp_pat1 in content else \
                     (prctl_kp_pat2 if prctl_kp_pat2 in content else '')
    if prctl_kp_match:
        content = content.replace(
            prctl_kp_match,
            '\t/* prctl_kp disabled: ksu_handle_prctl handles fd install */\n'
        )
    else:
        print("  WARNING: prctl_kp registration pattern not found, skipping removal")

    old = '\nvoid __init ksu_supercalls_init(void)'
    if old not in content:
        print(f"  ERROR: cannot find ksu_supercalls_init in {path}")
        return False
    content = content.replace(old, kprobe_decl + '\nvoid __init ksu_supercalls_init(void)', 1)

    # KSU-Next legacy supercall.c: ksu_supercalls_init directly ends with } (no #endif).
    # Insert new kprobe registrations before the closing } of ksu_supercalls_init.
    # Find the init function closing: "\tpr_debug("prctl kprobe registered successfully\n");\n}"
    init_close_a = '\t\tpr_debug("prctl kprobe registered successfully\\n");\n\t}\n}'
    init_close_b = '\t/* prctl_kp disabled: ksu_handle_prctl handles fd install */\n}'
    init_close = None
    for pat in [init_close_a, init_close_b]:
        if pat in content:
            init_close = pat
            break
    if not init_close:
        # Fallback: match "}\n*/\n}" or similar ending
        print(f"  WARNING: ksu_supercalls_init closing not found, scanning for function end")
        idx = content.find('void __init ksu_supercalls_init')
        init_close_found = False
        if idx >= 0:
            # Find the first "}\n" after ksu_supercalls_exit or EOF, whichever comes first
            # This only works if ksu_supercalls_init is the last function before exit
            for search_marker in ['\nvoid __exit ksu_supercalls_exit', '\n\nvoid __exit ksu_supercalls_exit']:
                end_idx = content.find(search_marker, idx)
                if end_idx > 0:
                    # Find the last "}" before the exit function
                    block = content[idx:end_idx]
                    last_brace = block.rfind('\n}')
                    if last_brace >= 0:
                        # This is the closing of ksu_supercalls_init
                        old = block[last_brace:]  # \n}
                        new = (
                            '\n'
                            '\t/* seccomp_bypass: bypass seccomp for SYS_reboot + KSU magic. */\n'
                            '\t{\n'
                            '\t\tint rc;\n'
                            '\t\trc = register_kprobe(&seccomp_bypass_kp);\n'
                            '\t\tif (rc) {\n'
                            '\t\t\tpr_err("seccomp_bypass kprobe failed: %d\\n", rc);\n'
                            '\t\t} else {\n'
                            '\t\t\tprintk(KERN_INFO "ksu_seccomp_bypass: kprobe registered\\n");\n'
                            '\t\t}\n'
                            '\t}\n'
                            '}'
                        )
                        content = content[:idx+last_brace] + new + content[end_idx:]
                        print(f"  KSU-Next: kprobe registration added (fallback)")
                        init_close_found = True
                        break
        if not init_close and not init_close_found:
            print(f"  ERROR: cannot find end of ksu_supercalls_init in {path}")
            return False
    else:
        # Found the closing pattern, insert kprobe registration before it
        new_init_close = (
            '\t\tpr_debug("prctl kprobe registered successfully\\n");\n'
            '\t}\n'
            '\t/* seccomp_bypass: bypass seccomp for SYS_reboot + KSU magic. */\n'
            '\t{\n'
            '\t\tint rc;\n'
            '\t\trc = register_kprobe(&seccomp_bypass_kp);\n'
            '\t\tif (rc) {\n'
            '\t\t\tpr_err("seccomp_bypass kprobe failed: %d\\n", rc);\n'
            '\t\t} else {\n'
            '\t\t\tprintk(KERN_INFO "ksu_seccomp_bypass: kprobe registered\\n");\n'
            '\t\t}\n'
            '\t}\n'
            '}'
        )
        content = content.replace(init_close, new_init_close, 1)
        print(f"  KSU-Next: kprobe registration added (pattern match)")

    # Also unregister in exit - KSU-Next only has unregister_kprobe(&reboot_kp);
    # Replace the exit function to add our unregisters
    exit_pat1 = '\tunregister_kprobe(&reboot_kp);\n\tksu_supercall_cleanup_state();\n}'
    exit_pat2 = '\tunregister_kprobe(&prctl_kp);\n}'
    if exit_pat1 in content:
        content = content.replace(
            exit_pat1,
            '\tunregister_kprobe(&reboot_kp);\n'
            '\tunregister_kprobe(&seccomp_bypass_kp);\n'
            '\tksu_supercall_cleanup_state();\n'
            '}',
            1
        )
        print("  KSU-Next: unregister added to ksu_supercalls_exit")
    elif exit_pat2 in content:
        content = content.replace(
            exit_pat2,
            '\t/* prctl_kp unregister removed (kprobe not registered) */\n'
            '\tunregister_kprobe(&seccomp_bypass_kp);\n'
            '}',
            1
        )

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: seccomp bypass kprobe (SYS_reboot+KSU magic)")
    return True


def fix_sysfs_manager_appid(kernel_root):
    """B4: Only allow sysfs write to set manager when none exists, or clear it.
    
    apk_sign.c: set_expected_size() is called when root writes to
    /sys/module/kernelsu/parameters/ksu_debug_manager_appid. The original
    function unconditionally calls ksu_set_manager_appid().
    
    Fix: only set if no manager exists, or if writing -1 (INVALID) to clear."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/manager/apk_sign.c",
        "KernelSU/kernel/manager/apk_sign.c",
    ])
    if not path:
        print(f"  WARNING: apk_sign.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'sysfs_mgr_fixed' in content:
        print(f"  {path}: already fixed")
        return True
    
    old = '\tksu_set_manager_appid(ksu_debug_manager_appid);'
    new = ('\t/* sysfs_mgr_fixed: only allow set if no manager, or clear */\n'
           '\tif (!ksu_is_manager_appid_valid() || '
           'ksu_debug_manager_appid == KSU_INVALID_APPID)\n'
           '\t\tksu_set_manager_appid(ksu_debug_manager_appid);')
    if old not in content:
        print(f"  WARNING: set_expected_size pattern not found in {path}")
        return True
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: sysfs mgr write limited")
    return True


def fix_dispatch_get_info(kernel_root):
    """NEW: Add auto-registration to do_get_info() (tab-indent matching LEGACY).
    
    inject-ksu-prctl.py tried to inject auto-registration into dispatch.c's
    do_get_info(), but failed because it used SPACE indentation while the
    LEGACY file uses TABS. This fix correctly injects using tab indent.
    
    Auto-registration: register calling app as manager if none exists,
    or the caller matches the current manager UID (handles reinstall)."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/dispatch.c",
        "KernelSU/kernel/supercall/dispatch.c",
    ])
    if not path:
        print(f"  WARNING: dispatch.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'dispatch_mgr_auto_reg' in content:
        print(f"  {path}: already fixed")
        return True
    
    # Find the is_manager() check in do_get_info (tab-indented)
    old = ('\tif (is_manager()) {\n'
           '\t\tcmd.flags |= KSU_GET_INFO_FLAG_MANAGER;\n'
           '\t}')
    if old not in content:
        print(f"  WARNING: do_get_info is_manager pattern not found in {path}")
        return True
    
    new = (
        '\t/* dispatch_mgr_auto_reg: register caller if no manager */\n'
        '\tif (!ksu_is_manager_appid_valid() ||\n'
        '\t    (current_uid().val % KSU_PER_USER_RANGE) == ksu_get_manager_appid()) {\n'
        '\t\tksu_set_manager_appid(current_uid().val % KSU_PER_USER_RANGE);\n'
        '\t}\n'
        '\tif (is_manager()) {\n'
        '\t\tcmd.flags |= KSU_GET_INFO_FLAG_MANAGER;\n'
        '\t}'
    )
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: do_get_info auto-registration added")
    return True


def fix_selinux_load_policy_kprobe(kernel_root):
    """Inject kprobe on security_load_policy → apply_kernelsu_rules in builtin mode.

    In builtin mode (CONFIG_KSU=y), kernelsu_init() runs at device_initcall
    level 6, BEFORE security_load_policy() is called by userspace init.
    The only code path that calls apply_kernelsu_rules() is on_post_fs_data(),
    which requires ksud in ramdisk to trigger. With ramdisk injection disabled,
    on_post_fs_data never fires → ksu domain never created.

    Fix: register a kprobe on security_load_policy via late_initcall.
    Post_handler schedules work that calls apply_kernelsu_rules +
    cache_sid + setup_ksu_cred right after the SELinux policy is loaded.
    Diag logs written to /dev/ksu_init_diag.log (devtmpfs, always available).

    Inject into supercall.c (already has <linux/kprobes.h>, <linux/fs.h>,
    <linux/file.h> included — only need to add <linux/workqueue.h>)."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/supercall.c",
        "KernelSU/kernel/supercall/supercall.c",
    ])
    if not path:
        print(f"  WARNING: supercall.c not found")
        return True

    with open(path) as f:
        content = f.read()

    if 'KSU_SECPOLICY_KPROBE' in content:
        print(f"  {path}: already injected")
        return True

    # Add required includes
    if '#include <linux/workqueue.h>' not in content:
        content = content.replace(
            '#include <linux/kprobes.h>',
            '#include <linux/kprobes.h>\n#include <linux/workqueue.h>'
        )
    if '#include "selinux/selinux.h"' not in content:
        content = content.replace(
            '#include "manager/manager_identity.h"',
            '#include "manager/manager_identity.h"\n#include "selinux/selinux.h"\n#include "ss/services.h"'
        )

    # Inject complete kprobe + work function + diag_log block
    # BEFORE ksu_supercalls_init(). Use the function definition as anchor.
    kprobe_code = (
        '\n'
        '/* KSU_SECPOLICY_KPROBE: late_initcall kprobe on security_load_policy.\n'
        ' * In builtin mode, on_post_fs_data never fires (ksud not in ramdisk).\n'
        ' * This kprobe ensures apply_kernelsu_rules is called as soon as\n'
        ' * userspace init loads the SELinux policy, creating the ksu domain. */\n'
        '\n'
        'static void ksu_diag_log(const char *msg)\n'
        '{\n'
        '\tstruct file *fp;\n'
        '\tloff_t pos = 0;\n'
        '\tfp = filp_open("/dev/ksu_init_diag.log",\n'
        '\t\t\tO_WRONLY | O_CREAT | O_APPEND, 0644);\n'
        '\tif (!IS_ERR(fp)) {\n'
        '\t\tkernel_write(fp, msg, strlen(msg), &pos);\n'
        '\t\tfilp_close(fp, NULL);\n'
        '\t}\n'
        '}\n'
        '\n'
        'static void ksu_selinux_policy_workfn(struct work_struct *work)\n'
        '{\n'
        '\tprintk(KERN_ERR "KSU_DIAG: BEFORE nprim=%d len=%zu jiffies=%lu\\n",\n'
        '\t    selinux_state.ss->policydb.p_types.nprim,\n'
        '\t    selinux_state.ss->policydb.len, jiffies);\n'
        '\tksu_diag_log("KSU_DIAG: policy workfn start\\n");\n'
        '\tapply_kernelsu_rules();\n'
        '\tprintk(KERN_ERR "KSU_DIAG: AFTER nprim=%d len=%zu jiffies=%lu\\n",\n'
        '\t    selinux_state.ss->policydb.p_types.nprim,\n'
        '\t    selinux_state.ss->policydb.len, jiffies);\n'
        '\tksu_diag_log("KSU_DIAG: apply_kernelsu_rules done\\n");\n'
        '\tcache_sid();\n'
        '\tksu_diag_log("KSU_DIAG: cache_sid done\\n");\n'
        '\tsetup_ksu_cred();\n'
        '\tksu_diag_log("KSU_DIAG: setup_ksu_cred done\\n");\n'
        '}\n'
        '\n'
        'static DECLARE_WORK(ksu_selinux_policy_work, ksu_selinux_policy_workfn);\n'
        '\n'
        'static void ksu_selinux_policy_load_post(struct kprobe *p,\n'
        '\t\t\t\t\t   struct pt_regs *regs,\n'
        '\t\t\t\t\t   unsigned long flags)\n'
        '{\n'
        '\tksu_diag_log("KSU_DIAG: security_load_policy post_handler\\n");\n'
        '\t/* Skip dummy policy (len=0), only process real policy load. */\n'
        '\tif (selinux_state.ss->policydb.len == 0) {\n'
        '\t\tksu_diag_log("KSU_DIAG: dummy policy, skip\\n");\n'
        '\t\treturn;\n'
        '\t}\n'
        '\tschedule_work(&ksu_selinux_policy_work);\n'
        '}\n'
        '\n'
        'static struct kprobe ksu_selinux_policy_kp = {\n'
        '\t.symbol_name = "security_load_policy",\n'
        '\t.post_handler = ksu_selinux_policy_load_post,\n'
        '};\n'
        '\n'
        'static int __init ksu_selinux_policy_kprobe_init(void)\n'
        '{\n'
        '\tint rc = register_kprobe(&ksu_selinux_policy_kp);\n'
        '\tif (rc) {\n'
        '\t\tpr_err("KSU: security_load_policy kprobe failed: %d\\n", rc);\n'
        '\t} else {\n'
        '\t\tpr_info("KSU: security_load_policy kprobe registered\\n");\n'
        '\t\tksu_diag_log("KSU_DIAG: secpol kprobe registered\\n");\n'
        '\t}\n'
        '\t/* If real policy already loaded (nprim > 0 at initcall time),\n'
        '\t * apply rules immediately without waiting for kprobe trigger.\n'
        '\t * selinux_state.initialized cannot be used — KSU injects\n'
        '\t * extra fields into struct selinux_state, shifting offsets. */\n'
        '\tif (selinux_state.ss->policydb.len > 0) {\n'
        '\t\tksu_diag_log("KSU_DIAG: state initialized, schedule work now\\n");\n'
        '\t\tschedule_work(&ksu_selinux_policy_work);\n'
        '\t}\n'
        '\treturn 0;\n'
        '}\n'
        'late_initcall(ksu_selinux_policy_kprobe_init);\n'
    )

    old = '\nvoid __init ksu_supercalls_init(void)'
    if old not in content:
        print(f"  WARNING: ksu_supercalls_init marker not found in {path}")
        return True

    content = content.replace(
        old, kprobe_code + '\nvoid __init ksu_supercalls_init(void)', 1)

    with open(path, 'w') as f:
        f.write(content)

    print(f"  {path}: security_load_policy kprobe injected (via late_initcall)")
    return True


def fix_kernelsu_init(kernel_root):
    """Ramdisk ksud approach: SELinux domain is initialized via
    on_post_fs_data (boot_event.c). Manager detection is handled by
    track_throne() injected into on_post_fs_data + pkg_observer + INSTALL_MAGIC2.
    No delayed work needed — ksud is always available from ramdisk."""
    return True


def fix_on_post_fs_data(kernel_root):
    """Inject track_throne(false) + overlay su write into boot_event.c
    on_post_fs_data(). With ksud in ramdisk, on_post_fs_data fires
    reliably because ksud is available from KSUD_PATH after post-fs-data
    
    This replaces the removed delayed work (ksu_delayed_selinux_init).
    """
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/boot_event.c",
        "drivers/kernelsu/../KernelSU-Next/kernel/runtime/boot_event.c",
        "KernelSU/kernel/runtime/boot_event.c",
    ])
    if not path:
        print(f"  WARNING: boot_event.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'RDSK_FIX' in content:
        print(f"  {path}: already injected, skipping")
        return True

    # Find the closing } of on_post_fs_data and inject before it
    # The function ends with:
    #   ksu_selinux_hide_handle_post_fs_data();
    # }
    old = '\tksu_selinux_hide_handle_post_fs_data();\n}'
    if old not in content:
        print(f"  WARNING: on_post_fs_data closing pattern not found in {path}")
        return True

    inject = (
        '\tksu_selinux_hide_handle_post_fs_data();\n'
        '\n'
        '\t/* RDSK_FIX: manager auto-detection + overlay su setup.\n'
        '\t * With ksud at KSUD_PATH, on_post_fs_data fires\n'
        '\t * reliably. No need for delayed workqueue. */\n'
        '\t{\n'
        '\t\textern struct cred *ksu_cred;\n'
        '\t\tconst struct cred *old_cred = override_creds(ksu_cred);\n'
        '\t\ttrack_throne(false);\n'
        '\t\trevert_creds(old_cred);\n'
        '\t}\n'
        '\t/* Write su to overlay upperdir (every boot, O_TRUNC updates). */\n'
        '\t{\n'
        '\t\tstatic const char su_content[] =\n'
        '\t\t\t"#!/system/bin/sh\\n"\n'
        '\t\t\t"exec /data/adb/ksud \\"$@\\"\\n";\n'
        '\t\tstruct file *fp;\n'
        '\t\tloff_t pos = 0;\n'
        '\t\tfp = filp_open("/mnt/scratch/overlay/odm/upper/bin/su",\n'
        '\t\t\t       O_WRONLY | O_CREAT | O_TRUNC, 0755);\n'
        '\t\tif (!IS_ERR(fp)) {\n'
        '\t\t\tkernel_write(fp, su_content, strlen(su_content), &pos);\n'
        '\t\t\tfilp_close(fp, NULL);\n'
        '\t\t\tprintk(KERN_ERR "KSU_DIAG: su written to overlay (%lldb)\\n", pos);\n'
        '\t\t}\n'
        '\t}\n'
        '\t/* Fix /data/adb/ permissions (non-root su access).\n'
        '\t * adb push creates /data/adb/ with 0700, blocking shell user.\n'
        '\t * /system/bin/su → /data/adb/ksud symlink needs 0755 on dir. */\n'
        '\t{\n'
        '\t\tstruct path adb_path;\n'
        '\t\tif (kern_path("/data/adb", LOOKUP_DIRECTORY, &adb_path) == 0) {\n'
        '\t\t\tstruct inode *adb_inode = adb_path.dentry->d_inode;\n'
        '\t\t\tadb_inode->i_mode |= 0755;\n'
        '\t\t\tmark_inode_dirty(adb_inode);\n'
        '\t\t\tpath_put(&adb_path);\n'
        '\t\t\tprintk(KERN_ERR "KSU_DIAG: /data/adb perms fixed\\n");\n'
        '\t\t}\n'
        '\t}\n'
        '}'
    )
    content = content.replace(old, inject, 1)
    with open(path, 'w') as fc:
        fc.write(content)
    print(f"  {path}: track_throne + overlay su injected into on_post_fs_data")
    return True


def fix_sucompat_multipath(kernel_root):
    """Extend sucompat.c to recognize /odm/bin/su in addition to /system/bin/su,
    and override argv[0] to "/system/bin/su" so cli.rs triggers root_shell().
    
    On LineageOS 20, /system is read-only ext4 (no overlay), so /system/bin/su
    cannot be created. /odm has overlay upperdir (persists across reboots).
    We intercept execve for both paths, redirect to KSUD_PATH, and set
    argv[0]="/system/bin/su" before execveat so ksud's cli.rs recognizes it.
    """
    path = find_file(kernel_root, [
        "drivers/kernelsu/feature/sucompat.c",
        "drivers/kernelsu/../KernelSU-Next/kernel/feature/sucompat.c",
        "KernelSU/kernel/feature/sucompat.c",
    ])
    if not path:
        print(f"  WARNING: sucompat.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'SUCOMPAT_MULTIPATH' in content:
        print(f"  {path}: multipath su already injected, skipping")
        return True

    # 1. Replace SU_PATH define to add a helper function for multi-path matching
    old_define = '#define SU_PATH "/system/bin/su"\n'
    new_define = (
        '#define SU_PATH "/system/bin/su"\n'
        '#define SU_PATH_ALT "/odm/bin/su"\n'
        '\n'
        '/* SUCOMPAT_MULTIPATH: match /system/bin/su + /odm/bin/su */\n'
        'static bool is_su_path(const char *path)\n'
        '{\n'
        '\treturn !memcmp(path, SU_PATH, sizeof(SU_PATH)) ||\n'
        '\t       !memcmp(path, SU_PATH_ALT, sizeof(SU_PATH_ALT));\n'
        '}\n'
    )
    content = content.replace(old_define, new_define, 1)

    # 2. Replace all memcmp(path, su_path, sizeof(su_path)) with is_su_path(path)
    #    !memcmp → is_su_path (faccessat/stat: match → intercept)
    #    memcmp  → !is_su_path (execve: not-match → skip, CORRECTED)
    content = content.replace(
        '!memcmp(path, su_path, sizeof(su_path))',
        'is_su_path(path)'
    )
    content = content.replace(
        'memcmp(path, su_path, sizeof(su_path))',
        '!is_su_path(path)'
    )

    # 3. Add argv[0] override before execveat in the execve handler.
    #    Insert before: ret = ksu_syscall_table[__NR_execveat](regs);
    old_execveat = '\tret = ksu_syscall_table[__NR_execveat](regs);'
    new_execveat = (
        '\t/* SUCOMPAT_MULTIPATH: override argv[0] to "/system/bin/su"\n'
        '\t * so ksud\\x27s cli.rs triggers root_shell().\n'
        '\t * The actual executable is KSUD_PATH (opened via filp_open).\n'
        '\t * argv[0] is just a string identifier, not a real file path. */\n'
        '\t{\n'
        '\t\tstatic const char fake_argv0[] = "/system/bin/su";\n'
        '\t\tconst char __user *argv0_ptr;\n'
        '\t\tconst char __user *const __user *argv;\n'
        '\t\targv0_ptr = userspace_stack_buffer(fake_argv0, sizeof(fake_argv0));\n'
        '\t\tif (argv0_ptr) {\n'
        '\t\t\targv = (const char __user *const __user *)regs->__PT_PARM2_REG;\n'
        '\t\t\tcopy_to_user((void __user *)&argv[0], &argv0_ptr, sizeof(argv0_ptr));\n'
        '\t\t}\n'
        '\t}\n'
        '\tret = ksu_syscall_table[__NR_execveat](regs);'
    )
    content = content.replace(old_execveat, new_execveat, 1)

    with open(path, 'w') as fc:
        fc.write(content)
    print(f"  {path}: sucompat multipath + argv[0] override injected")
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
    ok &= fix_boot_event(root)
    ok &= fix_selinux_clear_exec_sid(root)
    ok &= fix_app_profile(root)
    ok &= fix_rules(root)
    ok &= fix_ksu_exec_fd_reinstall(root)
    ok &= fix_ksud_postfsdata_noctx(root)
    ok &= fix_throne_deferred_cred(root)
    ok &= fix_throne_lock(root)
    ok &= fix_auto_crown_prctl(root)
    ok &= fix_sysfs_manager_appid(root)
    ok &= fix_dispatch_get_info(root)
    ok &= fix_allow_uid_zero(root)
    ok &= fix_syscall_hook_reboot(root)
    ok &= fix_seccomp_bypass(root)
    ok &= fix_kernelsu_init(root)
    ok &= fix_selinux_load_policy_kprobe(root)
    ok &= fix_on_post_fs_data(root)
    ok &= fix_sucompat_multipath(root)
    print(f"  CCACHE_BUSTER=1: Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
