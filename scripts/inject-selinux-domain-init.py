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

import sys, os, re


def find_file(kernel_root, candidates):
    for c in candidates:
        p = os.path.join(kernel_root, c)
        if os.path.exists(p):
            return p
    return None


def fix_boot_event(kernel_root):
    """Add apply_kernelsu_rules + cache_sid + setup_ksu_cred to on_post_fs_data()."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/boot_event.c",
        "KernelSU/kernel/runtime/boot_event.c",
    ])
    if not path:
        print(f"  ERROR: boot_event.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # Add include if not present
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

    if 'apply_kernelsu_rules()' in content:
        print(f"  {path}: already applied, skipping")
        return True

    # Insert before ksu_load_allow_list()
    marker = re.compile(r'^([ \t]*)ksu_load_allow_list\(\);', re.MULTILINE)
    m = marker.search(content)
    if not m:
        print(f"  ERROR: cannot find ksu_load_allow_list() in {path}")
        return False

    indent = m.group(1)
    block = (
        f'{indent}/* Initialize KSU SELinux domain. Build: __DATE__ __TIME__ */\n'
        f'{indent}apply_kernelsu_rules();\n'
        f'{indent}cache_sid();\n'
        f'{indent}setup_ksu_cred();\n'
        f'\n'
        f'{indent}ksu_load_allow_list();'
    )
    content, count = marker.subn(block, content, count=1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added calls to on_post_fs_data()")
    return True


def fix_selinux_clear_exec_sid(kernel_root):
    """NO-OP: do NOT clear exec_sid globally (breaks exec → untrusted_app domain with seccomp).
    Type_transition rules handle domain preservation across exec instead."""
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
        '    printk(KERN_INFO "ksu_debug: types before=%d\\n", db->p_types.nprim);\n'
        '    printk(KERN_INFO "ksu_debug: has domain type=%d\\n",\n'
        '        hashtab_search(db->p_types.table, "domain") != NULL);\n'
        '    {\n'
        '        bool _r = ksu_type(db, KERNEL_SU_DOMAIN, "domain");\n'
        '        printk(KERN_INFO "ksu_debug: ksu_type result=%d\\n", _r);\n'
        '    }\n'
        '    printk(KERN_INFO "ksu_debug: types after=%d\\n", db->p_types.nprim);\n'
        '    printk(KERN_INFO "ksu_debug: has ksu type=%d\\n",\n'
        '        hashtab_search(db->p_types.table, "ksu") != NULL);\n'
        '    printk(KERN_INFO "ksu_debug: ksu_type_transition result=%d\\n",\n'
        '        ksu_type_transition(db, KERNEL_SU_DOMAIN, "shell_exec", "process", KERNEL_SU_DOMAIN, ALL));\n'
        '    printk(KERN_INFO "ksu_debug: ksu_allow shell_exec result=%d\\n",\n'
        '        ksu_allow(db, KERNEL_SU_DOMAIN, "shell_exec", "file", "execute"));'
    )

    if old not in content:
        print(f"  ERROR: cannot find ksu_permissive marker in {path}")
        return False

    content = content.replace(old, new, 1)

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
        '\t_extern_ksu_install_fd();'
    )
    content = content.replace(marker, replacement, 1)

    # Also add the extern declaration
    if 'extern int _extern_ksu_install_fd' not in content:
        content = content.replace(
            '#include "selinux/selinux.h"',
            '#include "selinux/selinux.h"\n'
            'extern int _extern_ksu_install_fd(void);'
        )

    # Find and rename ksu_install_fd to _extern_ksu_install_fd
    sc_path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/supercall.c",
        "KernelSU/kernel/supercall/supercall.c",
    ])
    if not sc_path:
        print(f"  WARNING: supercall.c not found, fd reinstall might not compile")
        return True

    with open(sc_path) as f:
        sc_content = f.read()

    # Add __visible alias for ksu_install_fd (for extern use by ksud_integration)
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
             '\t\t\t * Change to __NR_getpid (allowed) so seccomp doesn't\n'
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
             '\treturn ksu_syscall_table[orig_nr](regs);\n"
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
    
    # Find the broken pattern and fix it
    # Find the deferred-cred injected block and replace everything from
    # "if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))" through the orphaned
    # "{ return false; }" with clean code:
    #   if (is_lock_held(path)) {
    #       return false;
    #   }
    anchor = 'if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH))'
    if anchor not in content:
        print(f"  WARNING: deferred-cred block not found in {path}")
        return True
    
    idx = content.find(anchor)
    # The orphan block (added by inject-deferred-ksu-cred.py) is:
    #  {\n\t\treturn false; // comment\n\t}
    # Find the orphan closing brace after the return false line
    search_start = content.find('\n {', idx)  # orphan block start
    if search_start < 0:
        print(f"  WARNING: orphan block start not found in {path}")
        return True
    orphan_close = content.find('\n\t}\n\n\tstruct file', search_start)
    if orphan_close < 0:
        orphan_close = content.find('\n\t}\n\n\tstruct file', search_start)
    if orphan_close < 0:
        print(f"  WARNING: orphan block close not found in {path}")
        return True
    orphan_close += len('\n\t}')
    
    replacement = (
        'if (is_lock_held(SYSTEM_PACKAGES_LIST_PATH)) {\n'
        '\t\t/* deferred_cred_fixed */\n'
        '\t\treturn false;\n'
        '\t}\n'
    )
    content = content[:idx] + replacement + content[orphan_close:]
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
    """Remove u:r:ksu:s0 from post-fs-data exec in KERNEL_SU_RC.
    
    The ksu SELinux domain isn't created until ~33s after boot (delayed
    workqueue). But post-fs-data fires at ~10-15s. Using exec u:r:ksu:s0
    fails because the domain doesn't exist yet. Without this fix, ksud
    never starts as a system daemon, and su symlink is never installed.
    
    Fix: use exec root -- (no SELinux context) for post-fs-data. The
    init context (u:r:init:s0) has sufficient permissions via KSU rules."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/ksud_integration.c",
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
    # Match: exec u:r:" KERNEL_SU_DOMAIN ":s0 root -- " KSUD_PATH " post-fs-data
    old = 'exec u:r:" KERNEL_SU_DOMAIN ":s0 root -- " KSUD_PATH " post-fs-data'
    new = 'exec root -- " KSUD_PATH " post-fs-data /* NOCTX_FIX */'
    if old not in content:
        print(f"  WARNING: post-fs-data exec pattern not found in {path}")
        return True
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: removed u:r:ksu:s0 from post-fs-data exec")
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


def fix_diag_allowed_for_su(kernel_root):
    """Add diagnostic printk to allowed_for_su() to trace 'grant root failed'."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/perm.c",
        "KernelSU/kernel/supercall/perm.c",
    ])
    if not path:
        print(f"  WARNING: perm.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'diag_allowed' in content:
        print(f"  {path}: already has diag")
        return True
    old = 'bool allowed_for_su(void)\n{\n\tbool is_allowed = is_manager() || ksu_is_allow_uid_for_current(current_uid().val);\n\treturn is_allowed;\n}'
    new = (
        'bool allowed_for_su(void)\n'
        '{\n'
        '\tbool is_mgr = is_manager();\n'
        '\tuid_t uid = current_uid().val;\n'
        '\tbool is_allow = ksu_is_allow_uid_for_current(uid);\n'
        '\tprintk(KERN_INFO "diag: allowed_for_su uid=%d is_mgr=%d is_allow=%d\\n",\n'
        '\t\tuid, is_mgr, is_allow);\n'
        '\treturn is_mgr || is_allow;\n'
        '}'
    )
    if old not in content:
        print(f"  WARNING: allowed_for_su pattern not found in {path}")
        return True
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added diag logs to allowed_for_su()")
    return True


def fix_diag_dispatch_eperm(kernel_root):
    """Add diagnostic printk to dispatch.c when returning EPERM from perm check."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/supercall/dispatch.c",
        "KernelSU/kernel/supercall/dispatch.c",
    ])
    if not path:
        print(f"  WARNING: dispatch.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'diag_eperm' in content:
        print(f"  {path}: already has diag")
        return True
    old = 'pr_warn("ksu ioctl: permission denied for cmd=0x%x uid=%d\\n",'
    new = (
        'printk(KERN_INFO "diag: EPERM cmd=0x%x uid=%d\\n",'
    )
    if old not in content:
        print(f"  WARNING: EPERM pattern not found in {path}")
        return True
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added diag to dispatch EPERM")
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
            '#include <linux/slab.h>\n#include <linux/seccomp.h>'
        )

    # Add the seccomp kprobe structure before ksu_supercalls_init
    kprobe_decl = '''

/* seccomp_bypass: bypass seccomp for KSU SYS_reboot magic, then install fd.
 * Android seccomp blocks __NR_reboot (142). libksud.so calls:
 *   syscall(SYS_reboot, KSU_INSTALL_MAGIC1=0xDEADBEEF, KSU_INSTALL_MAGIC2=0xCAFEBABE, 0, &fd)
 * We intercept secure_computing(), skip it for KSU magic, AND install the fd
 * via a second kprobe on __arm64_sys_reboot (always registered, not guarded by KSU_KPROBES_HOOK). */

/* Kprobe 1: bypass seccomp check for KSU SYS_reboot magic. */
static int seccomp_bypass_pre(struct kprobe *p, struct pt_regs *regs)
{
	struct pt_regs *user_regs = current_pt_regs();

	if (user_regs->orig_x0 == __NR_reboot) {
		unsigned long a0 = user_regs->regs[0];
		unsigned long a1 = user_regs->regs[1];
		if (a0 == KSU_INSTALL_MAGIC1 && a1 == KSU_INSTALL_MAGIC2) {
			return 1; /* Skip secure_computing → seccomp bypassed */
		}
	}
	return 0;
}

static struct kprobe seccomp_bypass_kp = {
	.symbol_name = "secure_computing",
	.pre_handler = seccomp_bypass_pre,
};

/* Kprobe 2: always-registered reboot handler (not guarded by KSU_KPROBES_HOOK).
 * Installs the KSU driver fd when SYS_reboot is called with KSU magic.
 * The seccomp_bypass kprobe above guarantees this handler is reached. */
static int ksu_reboot_kprobe_pre(struct kprobe *p, struct pt_regs *regs)
{
	struct pt_regs *real_regs = PT_REAL_REGS(regs);
	unsigned long magic1 = PT_REGS_PARM1(real_regs);
	unsigned long magic2 = PT_REGS_PARM2(real_regs);

	if (magic1 == KSU_INSTALL_MAGIC1 && magic2 == KSU_INSTALL_MAGIC2) {
		unsigned long arg4 = PT_REGS_SYSCALL_PARM4(real_regs);
		int __user *out_fd = (int __user *)arg4;

		if (out_fd) {
			int fd = ksu_install_fd();
			if (fd >= 0 && !copy_to_user(out_fd, &fd, sizeof(fd))) {
				/* Override return value: 0 = success */
				PT_REGS_RC(real_regs) = 0;
				return 1; /* Skip original __arm64_sys_reboot */
			}
		}
	}
	return 0;
}

static struct kprobe ksu_reboot_kp = {
	.symbol_name = REBOOT_SYMBOL,
	.pre_handler = ksu_reboot_kprobe_pre,
};
'''

    # Insert kprobe declaration before ksu_supercalls_init
    old = '\nvoid __init ksu_supercalls_init(void)'
    if old not in content:
        print(f"  ERROR: cannot find ksu_supercalls_init in {path}")
        return False
    content = content.replace(old, kprobe_decl + '\nvoid __init ksu_supercalls_init(void)', 1)

    # In the legacy branch, ksu_supercalls_init ends with:
    #   #ifdef KSU_KPROBES_HOOK
    #       register_kprobe(&reboot_kp);
    #   #endif
    #   }
    # We add our two kprobes after #endif, before }.
    old = '#endif\n}'
    if old not in content:
        print(f"  ERROR: cannot find end of ksu_supercalls_init in {path}")
        return False
    
    new = (
        '#endif\n'
        '\n'
        '\t/* seccomp_bypass: bypass seccomp for SYS_reboot + KSU magic. */\n'
        '\t{\n'
        '\t\tint rc;\n'
        '\t\trc = register_kprobe(&seccomp_bypass_kp);\n'
        '\t\tif (rc) {\n'
        '\t\t\tpr_err("seccomp_bypass kprobe failed: %d\\n", rc);\n'
        '\t\t} else {\n'
        '\t\t\tpr_debug("seccomp_bypass kprobe registered\\n");\n'
        '\t\t}\n'
        '\n'
        '\t\trc = register_kprobe(&ksu_reboot_kp);\n'
        '\t\tif (rc) {\n'
        '\t\t\tpr_err("ksu_reboot kprobe failed: %d\\n", rc);\n'
        '\t\t} else {\n'
        '\t\t\tpr_debug("ksu_reboot kprobe registered\\n");\n'
        '\t\t}\n'
        '\t}\n'
        '}'
    )
    content = content.replace(old, new, 1)

    # Also unregister in exit
    old_exit = '\tunregister_kprobe(&prctl_kp);\n}'
    if old_exit in content:
        content = content.replace(
            old_exit,
            '\tunregister_kprobe(&prctl_kp);\n'
            '\tunregister_kprobe(&seccomp_bypass_kp);\n'
            '}',
            1
        )

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: seccomp bypass kprobe (SYS_reboot+KSU magic)")
    return True


def fix_throne_crown_manager(kernel_root):
    """B1: Prevent crown_manager() from overwriting a valid manager.
    
    throne_tracker.c's crown_manager() unconditionally sets ksu_manager_appid
    when scan_manager() finds a matching APK. If SukiSU APK somehow matched
    EXPECTED_MANAGER_HASH, it could take over as manager.
    
    Fix: only set manager UID if no manager exists yet."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/manager/throne_tracker.c",
        "KernelSU/kernel/manager/throne_tracker.c",
    ])
    if not path:
        print(f"  WARNING: throne_tracker.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'crown_fixed' in content:
        print(f"  {path}: already fixed")
        return True
    
    old = '\t\t\tksu_set_manager_appid(np->uid);'
    new = '\t\t\tif (!ksu_is_manager_appid_valid()) { ksu_set_manager_appid(np->uid); } /* crown_fixed */'
    if old not in content:
        print(f"  WARNING: crown_manager pattern not found in {path}")
        return True
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: crown_manager only sets if no manager exists")
    return True


def fix_kpm_manager_uid_export(kernel_root):
    """B2: Make sukisu_set_manager_uid static (not exported) + remove force.
    
    kpm/compact.c exports sukisu_set_manager_uid() as a symbol that KPM
    modules can find. With force=1, any KPM module can bypass APK signature
    checks and overwrite ksu_manager_appid.
    
    Fix: change force parameter logic and make function static."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/kpm/compact.c",
        "KernelSU/kernel/kpm/compact.c",
    ])
    if not path:
        print(f"  WARNING: kpm/compact.c not found")
        return True
    with open(path) as f:
        content = f.read()
    if 'kpm_uid_fixed' in content:
        print(f"  {path}: already fixed")
        return True
    
    old = ('static void sukisu_set_manager_uid(uid_t uid, int force)\n'
           '{\n'
           '    if (force || ksu_manager_appid == -1)\n'
           '        ksu_manager_appid = uid;')
    new = ('/* kpm_uid_fixed: static function, force removed */\n'
           'static void sukisu_set_manager_uid(uid_t uid, int force)\n'
           '{\n'
           '    (void)force; /* parameter kept for ABI but ignored */\n'
           '    if (ksu_manager_appid == -1)\n'
           '        ksu_manager_appid = uid;')
    if old not in content:
        print(f"  WARNING: sukisu_set_manager_uid pattern not found in {path}")
        return True
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: sukisu_set_manager_uid force removed")
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


def fix_kernelsu_init(kernel_root):
    """Add apply_kernelsu_rules + cache_sid + setup_ksu_cred directly in
    kernelsu_init(), before the final 'return 0;'. This runs at
    device_initcall level, after SELinux is fully initialized."""
    path = find_file(kernel_root, [
        "drivers/kernelsu/core/init.c",
        "KernelSU/kernel/core/init.c",
    ])
    if not path:
        print(f"  ERROR: core/init.c not found")
        return False

    with open(path) as f:
        content = f.read()

    # Check if our injection already exists (the comment is unique to our code)
    if 'KSU SELinux domain (SELinux is fully initialized at this point)' in content:
        print(f"  {path}: already injected, skipping")
        return True

    # Add includes if not present
    if '#include "selinux/selinux.h"' not in content:
        content = content.replace(
            '#include "klog.h"',
            '#include "klog.h"\n#include "selinux/selinux.h"'
        )
    if '#include <linux/workqueue.h>' not in content:
        content = content.replace(
            '#include <linux/export.h>',
            '#include <linux/export.h>\n#include <linux/workqueue.h>'
        )
    if '#include <linux/delay.h>' not in content:
        content = content.replace(
            '#include <linux/export.h>',
            '#include <linux/export.h>\n#include <linux/delay.h>'
        )
    if '#include <linux/kmod.h>' not in content:
        content = content.replace(
            '#include <linux/export.h>',
            '#include <linux/export.h>\n#include <linux/kmod.h>'
        )
    if '#include "manager/manager_identity.h"' not in content:
        content = content.replace(
            '#include "klog.h"',
            '#include "klog.h"\n#include "manager/manager_identity.h"\n#include "manager/throne_tracker.h"'
        )

    # Add DECLARE_DELAYED_WORK + work function BEFORE kernelsu_init
    # (must be declared before the function that uses it)
    work_decl = '''

/* Delayed init: SELinux domain + auto-crown manager UID.
 * Runs ~30s after boot (policy fully loaded, /data accessible). */
static void ksu_delayed_selinux_init(struct work_struct *work)
{
		printk(KERN_INFO "ksu_debug: delayed init executing\\n");
	apply_kernelsu_rules();
	cache_sid();
	setup_ksu_cred();
	/* Fix cold boot grant root: set manager UID before app starts. */
	{
		const struct cred *old_cred2 = override_creds(ksu_cred);
		/* Call track_throne() first (it may already set manager_appid) */
		track_throne(false);
		/* If track_throne() failed (e.g. due to is_lock_held race), */
		/* scan packages.list directly via kernel_read */
		if (!ksu_is_manager_appid_valid()) {
			struct file *f2 = filp_open("/data/system/packages.list",
				O_RDONLY, 0);
			printk(KERN_INFO "ksu_dbg: open=%ld\\n",
				IS_ERR(f2) ? PTR_ERR(f2) : 0L);
			if (!IS_ERR(f2)) {
				loff_t sz2 = i_size_read(file_inode(f2));
				printk(KERN_INFO "ksu_dbg: plist sz=%lld\\n", sz2);
				if (sz2 > 0 && sz2 < 131072) {
					char *bf = kvmalloc((size_t)sz2 + 1,
						GFP_KERNEL);
					printk(KERN_INFO "ksu_dbg: alloc=%s\\n",
						bf ? "ok" : "fail");
					if (bf) {
						loff_t rp2 = 0;
						ssize_t nr2 = kernel_read(f2, bf,
							(size_t)sz2, &rp2);
						printk(KERN_INFO "ksu_dbg: read=%zd/%lld\\n",
							nr2, sz2);
						if (nr2 == (ssize_t)sz2) {
							char *hit2 = strstr(bf,
								KSU_MANAGER_PACKAGE);
							printk(KERN_INFO "ksu_dbg: strstr=%s\\n",
								hit2 ? "found" : "miss");
							if (hit2) {
								hit2 +=
									strlen(
									KSU_MANAGER_PACKAGE);
								while (*hit2 == 32)
									hit2++;
								if (*hit2 >= 48
									&& *hit2 <= 57) {
									uid_t vu2 =
									simple_strtoul(
									hit2, NULL, 10);
									ksu_set_manager_appid(
										vu2);
									printk(KERN_INFO
										"ksu_dbg: set UID=%d\\n",
										vu2);
								} else {
									printk(KERN_INFO
									"ksu_dbg: no digit\\n");
								}
							} else {
								printk(KERN_INFO
									"ksu_dbg: miss\\n");
							}
						}
						kvfree(bf);
					}
				}
				filp_close(f2, NULL);
			}
		}
		revert_creds(old_cred2);
	}
	if (ksu_manager_appid != -1)
		printk(KERN_INFO "ksu_debug: mgr=%d fallback\\n", ksu_manager_appid);
	else
		printk(KERN_INFO "ksu_debug: mgr still INVALID\\n");
	/* Make su available via overlay upperdir write (call_usermodehelper disabled).
	 * Uses kernel VFS directly: filp_open + kernel_write to /mnt/scratch/overlay/odm/upper/bin/su.
	 * The overlay upperdir (/mnt/scratch, f2fs) persists across reboots.
	 * On first boot, try /data/local/tmp/su as fallback. */
	{
		static const char su_content[] =
			"#!/system/bin/sh\\n"
			"exec /data/adb/ksu/bin/ksud debug su -g\\n";
		const char *su_paths[] = {
			"/mnt/scratch/overlay/odm/upper/bin/su",
			"/data/local/tmp/su",
		};
		int i;
		for (i = 0; i < 2; i++) {
			const struct cred *old_cred3 = override_creds(ksu_cred);
			struct file *fp_su;
			loff_t pos_su = 0;
			fp_su = filp_open(su_paths[i],
					  O_WRONLY | O_CREAT | O_TRUNC, 0755);
			if (IS_ERR(fp_su)) {
				printk(KERN_INFO "ksu_diag: su@%s=%ld\\n",
				       su_paths[i], PTR_ERR(fp_su));
			} else {
				kernel_write(fp_su, su_content,
					     strlen(su_content), &pos_su);
				filp_close(fp_su, NULL);
				printk(KERN_INFO "ksu_diag: su@%s (%lldb)\\n",
				       su_paths[i], pos_su);
			}
			revert_creds(old_cred3);
		}
	}
	printk(KERN_INFO "ksu_debug: delayed init complete\\n");
}
static DECLARE_DELAYED_WORK(ksu_delayed_selinux_work, ksu_delayed_selinux_init);
'''
    # Insert before kernelsu_init definition
    content = content.replace(
        'int __init kernelsu_init(void)',
        work_decl + '\nint __init kernelsu_init(void)',
        1
    )

    # Find the final return 0; in kernelsu_init() and insert before it.
    # Using str.replace() to avoid Python re.sub's backslash interpretation
    # (re.sub converts \\n in replacement to actual newline chars).
    old_tail = '\treturn 0;\n}\n\nvoid __exit kernelsu_exit'
    if old_tail not in content:
        print(f"  ERROR: cannot find kernelsu_init() end marker in {path}")
        return False

    new_tail = (
        '\t/* Defer SELinux domain init: policydb not ready at device_initcall. */\n'
        '\t/* Schedule delayed work to run ~30s after boot (policy fully loaded). */\n'
        '\tprintk(KERN_INFO "ksu_debug: scheduling delayed ksu domain init\\n");\n'
        '\tschedule_delayed_work(&ksu_delayed_selinux_work, 30 * HZ);\n'
        '\n'
        '\treturn 0;\n'
        '}\n'
        '\n'
        'void __exit kernelsu_exit'
    )
    content = content.replace(old_tail, new_tail, 1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: added calls to kernelsu_init()")
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
    ok &= fix_ksud_postfsdata_noctx(root)
    ok &= fix_throne_deferred_cred(root)
    ok &= fix_throne_lock(root)
    ok &= fix_throne_crown_manager(root)
    ok &= fix_kpm_manager_uid_export(root)
    ok &= fix_auto_crown_prctl(root)
    ok &= fix_sysfs_manager_appid(root)
    ok &= fix_dispatch_get_info(root)
    ok &= fix_allow_uid_zero(root)
    ok &= fix_diag_allowed_for_su(root)
    ok &= fix_diag_dispatch_eperm(root)
    ok &= fix_syscall_hook_reboot(root)
    ok &= fix_kernelsu_init(root)
    print(f"  CCACHE_BUSTER=1: Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
