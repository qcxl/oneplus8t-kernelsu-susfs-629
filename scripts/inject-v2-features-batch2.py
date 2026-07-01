#!/usr/bin/env python3
"""
inject-v2-features-batch2.py - Port Batch 2 v2.2.0 features to v1.5.5.

Adds:
1. susfs_set_hide_sus_mnts_for_non_su_procs() - toggle mount hiding
2. susfs_generic_fillattr_spoofer() - selective kstat spoofing
3. susfs_show_map_vma_spoofer() - selective map_vma spoofing  
4. susfs_add_sus_path_loop() + susfs_run_sus_path_loop() - periodic path re-flag
5. VFS hook updates in stat.c and task_mmu.c
6. Dispatch entries for new commands
"""

import sys, os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

def insert_before_line(path, marker, text):
    p = os.path.join(KERNEL_ROOT, path)
    with open(p) as f: lines = f.read().split('\n')
    for i, line in enumerate(lines):
        if marker in line:
            lines.insert(i, text)
            with open(p, 'w') as f: f.write('\n'.join(lines))
            return True
    print(f"  ERROR: marker '{marker}' not found in {path}")
    return False

def replace_in_file(path, old, new):
    p = os.path.join(KERNEL_ROOT, path)
    with open(p) as f: content = f.read()
    if old not in content:
        print(f"  ERROR: pattern not found in {path}")
        return False
    content = content.replace(old, new, 1)
    with open(p, 'w') as f: f.write(content)
    return True

def append_to_file(path, text):
    with open(os.path.join(KERNEL_ROOT, path), 'a') as f:
        f.write(text)

# ============================================================
# 1. susfs_def.h: add new CMD and flags
# ============================================================
def inject_susfs_def_h():
    path = "include/linux/susfs_def.h"
    cmds = (
        '\n'
        '/* added by Batch 2 port */\n'
        '#define CMD_SUSFS_ADD_SUS_PATH_LOOP 0x55553\n'
    )
    # Insert CMD_SUSFS_ADD_SUS_PATH_LOOP before CMD_SUSFS_ADD_SUS_MOUNT
    if not insert_before_line(path, '#define CMD_SUSFS_ADD_SUS_MOUNT', cmds):
        return False
    print("  [OK] susfs_def.h: added CMD")
    return True

# ============================================================
# 2. susfs.h: add struct + declarations
# ============================================================
def inject_susfs_h():
    path = "include/linux/susfs.h"
    structs = (
        '\n'
        '/* hide_sus_mnts for non-su procs */\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n'
        'struct st_susfs_hide_sus_mnts_for_non_su_procs {\n'
        '\tbool                                    enabled;\n'
        '\tint                                     err;\n'
        '};\n'
        '#endif\n'
    )
    decls = (
        '\n'
        '/* hide_sus_mnts */\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n'
        'void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n'
        'void susfs_generic_fillattr_spoofer(struct inode *inode, struct kstat *stat);\n'
        'void susfs_show_map_vma_spoofer(struct inode *inode, dev_t *out_dev, unsigned long *out_ino);\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n'
        'void susfs_add_sus_path_loop(void __user **user_info);\n'
        '#endif\n'
    )
    if not insert_before_line(path, '/* susfs_init */', structs + decls):
        return False
    print("  [OK] susfs.h: added struct + declarations")
    return True

# ============================================================
# 3. susfs.c: add all 4 new functions + update susfs_init
# ============================================================
def inject_susfs_c():
    path = "fs/susfs.c"
    
    # First check if already injected
    with open(os.path.join(KERNEL_ROOT, path)) as f:
        content = f.read()
    if 'susfs_set_hide_sus_mnts_for_non_su_procs' in content:
        print("  [SKIP] susfs.c: already has Batch 2 features")
        return True

    # Includes: ksu_cred for workqueue credential override
    includes = (
        '#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n'
        'extern struct cred *ksu_cred;\n'
        '#endif\n'
    )

    # Global variable for hide_sus_mnts (extern - defined in proc_namespace.c by 50_add patch)
    hide_var = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n'
        'extern bool susfs_hide_sus_mnts_for_all_procs;\n'
        '#endif\n'
    )

    # Function ①: hide_sus_mnts setter
    hide_func = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n'
        'void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info) {\n'
        '\tstruct st_susfs_hide_sus_mnts_for_non_su_procs info = {0};\n'
        '\tif (copy_from_user(&info, (struct st_susfs_hide_sus_mnts_for_non_su_procs __user*)*user_info, sizeof(info))) {\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\tWRITE_ONCE(susfs_hide_sus_mnts_for_all_procs, info.enabled);\n'
        '\tSUSFS_LOGI("susfs_hide_sus_mnts_for_all_procs: %d\\n", info.enabled);\n'
        '\tinfo.err = 0;\n'
        'out:\n'
        '\tif (copy_to_user(&((struct st_susfs_hide_sus_mnts_for_non_su_procs __user*)*user_info)->err, &info.err, sizeof(info.err)))\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\tSUSFS_LOGI("CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS -> ret: %d\\n", info.err);\n'
        '}\n'
        '#endif /* CONFIG_KSU_SUSFS_SUS_MOUNT */\n'
    )

    # Function ②: fillattr_spoofer (non-RCU hash, compatible with v1.5.5)
    fillattr_func = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n'
        'void susfs_generic_fillattr_spoofer(struct inode *inode, struct kstat *stat) {\n'
        '\tstruct st_susfs_sus_kstat_hlist *entry = NULL;\n'
        '\tunsigned long target_ino = inode->i_ino;\n'
        '\n'
        '\thash_for_each_possible(SUS_KSTAT_HLIST, entry, node, target_ino) {\n'
        '\t\tif (entry->target_ino == target_ino) {\n'
        '\t\t\tstat->dev = entry->info.spoofed_dev;\n'
        '\t\t\tstat->ino = entry->info.spoofed_ino;\n'
        '\t\t\tstat->nlink = entry->info.spoofed_nlink;\n'
        '\t\t\tstat->size = entry->info.spoofed_size;\n'
        '\t\t\tstat->atime.tv_sec = entry->info.spoofed_atime_tv_sec;\n'
        '\t\t\tstat->atime.tv_nsec = entry->info.spoofed_atime_tv_nsec;\n'
        '\t\t\tstat->mtime.tv_sec = entry->info.spoofed_mtime_tv_sec;\n'
        '\t\t\tstat->mtime.tv_nsec = entry->info.spoofed_mtime_tv_nsec;\n'
        '\t\t\tstat->ctime.tv_sec = entry->info.spoofed_ctime_tv_sec;\n'
        '\t\t\tstat->ctime.tv_nsec = entry->info.spoofed_ctime_tv_nsec;\n'
        '\t\t\tstat->blocks = entry->info.spoofed_blocks;\n'
         '\t\t\tstat->blksize = entry->info.spoofed_blksize;\n'
         '\t\t\treturn;\n'
        '\t\t}\n'
         '\t}\n'
         '}\n'
         '#endif /* CONFIG_KSU_SUSFS_SUS_KSTAT */\n'
     )

     # Function ③: show_map_vma_spoofer (non-RCU hash)
     mapvma_func = (
         '\n'
         '#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n'
         'void susfs_show_map_vma_spoofer(struct inode *inode, dev_t *out_dev, unsigned long *out_ino) {\n'
         '\tstruct st_susfs_sus_kstat_hlist *entry = NULL;\n'
         '\tunsigned long target_ino = inode->i_ino;\n'
         '\n'
         '\thash_for_each_possible(SUS_KSTAT_HLIST, entry, node, target_ino) {\n'
         '\t\tif (entry->target_ino == target_ino) {\n'
         '\t\t\t*out_dev = entry->info.spoofed_dev;\n'
         '\t\t\t*out_ino = entry->info.spoofed_ino;\n'
         '\t\t\treturn;\n'
         '\t\t}\n'
         '\t}\n'
         '}\n'
         '#endif /* CONFIG_KSU_SUSFS_SUS_KSTAT */\n'
     )

    # Function ④: sus_path_loop infrastructure + function + workqueue
    # Uses a local struct with err field (v2.2.0 protocol), converts to v1.5.5 struct internally
    path_loop_infra = (
        '\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n'
        '/* v2.2.0 compatible struct with err field for sus_path_loop */\n'
        'struct st_susfs_sus_path_v2 {\n'
        '\tunsigned long                    target_ino;\n'
        '\tchar                             target_pathname[SUSFS_MAX_LEN_PATHNAME];\n'
        '\tunsigned int                     i_uid;\n'
        '\tint                              err;\n'
        '};\n'
        '\n'
        'static DEFINE_MUTEX(susfs_mutex_lock_sus_path);\n'
        'static LIST_HEAD(LH_SUS_PATH_LOOP);\n'
        '\n'
        'void susfs_add_sus_path_loop(void __user **user_info) {\n'
        '\tstruct st_susfs_sus_path_v2 info = {0};\n'
        '\tstruct st_susfs_sus_path_list *new_list = NULL;\n'
        '\n'
        '\tif (copy_from_user(&info, (struct st_susfs_sus_path_v2 __user*)*user_info, sizeof(info))) {\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\n'
        '\tif (*info.target_pathname == \'\\0\') {\n'
        '\t\tinfo.err = -EINVAL;\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\n'
        '\tnew_list = kzalloc(sizeof(struct st_susfs_sus_path_list), GFP_KERNEL);\n'
        '\tif (!new_list) {\n'
        '\t\tinfo.err = -ENOMEM;\n'
        '\t\tgoto out;\n'
        '\t}\n'
        '\tstrncpy(new_list->info.target_pathname, info.target_pathname, SUSFS_MAX_LEN_PATHNAME - 1);\n'
        '\tstrncpy(new_list->target_pathname, info.target_pathname, SUSFS_MAX_LEN_PATHNAME - 1);\n'
        '\tINIT_LIST_HEAD(&new_list->list);\n'
        '\tmutex_lock(&susfs_mutex_lock_sus_path);\n'
        '\tlist_add_tail(&new_list->list, &LH_SUS_PATH_LOOP);\n'
        '\tmutex_unlock(&susfs_mutex_lock_sus_path);\n'
        '\tSUSFS_LOGI("target_pathname: \'%s\', added to LH_SUS_PATH_LOOP\\n", new_list->target_pathname);\n'
        '\tinfo.err = 0;\n'
        'out:\n'
        '\tif (copy_to_user(&((struct st_susfs_sus_path_v2 __user*)*user_info)->err, &info.err, sizeof(info.err)))\n'
        '\t\tinfo.err = -EFAULT;\n'
        '\tSUSFS_LOGI("CMD_SUSFS_ADD_SUS_PATH_LOOP -> ret: %d\\n", info.err);\n'
        '}\n'
        '\n'
        'static void susfs_run_sus_path_loop(void) {\n'
        '\tstruct st_susfs_sus_path_list *cursor = NULL;\n'
        '\tstruct path path;\n'
        '\tstruct inode *inode;\n'
        '\n'
        '\tlist_for_each_entry(cursor, &LH_SUS_PATH_LOOP, list) {\n'
        '\t\tif (!kern_path(cursor->target_pathname, 0, &path)) {\n'
        '\t\t\tinode = d_backing_inode(path.dentry);\n'
        '\t\t\tif (inode) {\n'
        '\t\t\t\tinode->i_state |= INODE_STATE_SUS_PATH;\n'
        '\t\t\t\tSUSFS_LOGI("re-flag SUS_PATH on path \'%s\'\\n", cursor->target_pathname);\n'
        '\t\t\t}\n'
        '\t\t\tpath_put(&path);\n'
        '\t\t}\n'
        '\t}\n'
        '}\n'
        '\n'
        'struct work_struct susfs_extra_works;\n'
        'static void susfs_run_extra_works(struct work_struct *work) {\n'
        '\tconst struct cred *saved;\n'
        '\tif (!ksu_cred)\n'
        '\t\treturn;\n'
        '\tsaved = override_creds(ksu_cred);\n'
        '\tsusfs_run_sus_path_loop();\n'
        '\trevert_creds(saved);\n'
        '}\n'
        '#endif /* CONFIG_KSU_SUSFS_SUS_PATH */\n'
    )

    # Combine all code
    combined = includes + hide_var + hide_func + fillattr_func + mapvma_func + path_loop_infra

    # Insert before /* susfs_init */
    if not insert_before_line(path, '/* susfs_init */', combined):
        return False

    # Update susfs_init to add INIT_WORK
    old_init = (
        'void susfs_init(void) {\n'
        '\tspin_lock_init(&susfs_spin_lock);\n'
        '#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME\n'
        '\tspin_lock_init(&susfs_uname_spin_lock);\n'
        '\tsusfs_my_uname_init();\n'
        '#endif\n'
        '\tSUSFS_LOGI("susfs is initialized! version: " SUSFS_VERSION " \\n");\n'
        '}'
    )
    new_init = (
        'void susfs_init(void) {\n'
        '\tspin_lock_init(&susfs_spin_lock);\n'
        '#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME\n'
        '\tspin_lock_init(&susfs_uname_spin_lock);\n'
        '\tsusfs_my_uname_init();\n'
        '#endif\n'
        '#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n'
        '\tINIT_WORK(&susfs_extra_works, susfs_run_extra_works);\n'
        '\tSUSFS_LOGI("susfs_extra_works initialized\\n");\n'
        '#endif\n'
        '\tSUSFS_LOGI("susfs is initialized! version: " SUSFS_VERSION " \\n");\n'
        '}'
    )
    if not replace_in_file(path, old_init, new_init):
        return False

    print("  [OK] susfs.c: added 4 functions + init update")
    return True

# ============================================================
# 4. VFS hooks: update stat.c call site
# ============================================================
def patch_stat_c():
    path = "fs/stat.c"
    # Replace old function call + extern with new
    old_extern = 'extern void susfs_sus_ino_for_generic_fillattr(unsigned long ino, struct kstat *stat);\n'
    new_extern = 'extern void susfs_generic_fillattr_spoofer(struct inode *inode, struct kstat *stat);\n'
    if not replace_in_file(path, old_extern, new_extern):
        return False
    
    old_call = 'susfs_sus_ino_for_generic_fillattr(inode->i_ino, stat);'
    new_call = 'susfs_generic_fillattr_spoofer(inode, stat);'
    if not replace_in_file(path, old_call, new_call):
        return False
    
    print("  [OK] fs/stat.c: updated fillattr call")
    return True

# ============================================================
# 5. VFS hooks: update task_mmu.c call site
# ============================================================
def patch_task_mmu():
    path = "fs/proc/task_mmu.c"
    old_extern = 'extern void susfs_sus_ino_for_show_map_vma(unsigned long ino, dev_t *out_dev, unsigned long *out_ino);\n'
    new_extern = 'extern void susfs_show_map_vma_spoofer(struct inode *inode, dev_t *out_dev, unsigned long *out_ino);\n'
    if not replace_in_file(path, old_extern, new_extern):
        return False
    
    old_call = 'susfs_sus_ino_for_show_map_vma(inode->i_ino, &dev, &ino);'
    new_call = 'susfs_show_map_vma_spoofer(inode, &dev, &ino);'
    if not replace_in_file(path, old_call, new_call):
        return False
    
    print("  [OK] fs/proc/task_mmu.c: updated show_map_vma call")
    return True

# ============================================================
# 6. Dispatch: add entries to inject-susfs-dispatch.py template
# ============================================================
def patch_dispatch_template():
    script_path = "/Users/weifeng/Downloads/OnePlus8T/build-kernelsu-susfs/scripts/inject-susfs-dispatch.py"
    with open(script_path) as f: content = f.read()
    
    if 'CMD_SUSFS_ADD_SUS_PATH_LOOP' in content:
        print("  [SKIP] dispatch template: already has Batch 2 entries")
        return True
    
    # IOCTL handler: add cases before CMD_SUSFS_ADD_SUS_MAP
    old_ioctl_anchor = '\tcase CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING:\n'
    new_ioctl_add = (
        '\tcase CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS:\n'
        '\t\tsusfs_set_hide_sus_mnts_for_non_su_procs(&uarg);\n'
        '\t\treturn 0;\n'
        '\tcase CMD_SUSFS_ADD_SUS_PATH_LOOP:\n'
        '\t\tsusfs_add_sus_path_loop(&uarg);\n'
        '\t\treturn 0;\n'
    )
    content = content.replace(old_ioctl_anchor, old_ioctl_anchor + new_ioctl_add, 1)
    
    # Reboot handler: same additions
    old_reboot_anchor = '\t\tcase CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING:\n'
    new_reboot_add = (
        '\t\tcase CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS:\n'
        '\t\t\tsusfs_set_hide_sus_mnts_for_non_su_procs(&uarg);\n'
        '\t\t\treturn 0;\n'
        '\t\tcase CMD_SUSFS_ADD_SUS_PATH_LOOP:\n'
        '\t\t\tsusfs_add_sus_path_loop(&uarg);\n'
        '\t\t\treturn 0;\n'
    )
    content = content.replace(old_reboot_anchor, old_reboot_anchor + new_reboot_add, 1)
    
    with open(script_path, 'w') as f: f.write(content)
    print("  [OK] dispatch template: added Batch 2 entries")
    return True

# ============================================================
# Main
# ============================================================
def main():
    ok = True
    ok &= inject_susfs_def_h()
    ok &= inject_susfs_h()
    ok &= inject_susfs_c()
    ok &= patch_stat_c()
    ok &= patch_task_mmu()
    ok &= patch_dispatch_template()
    print(f"\n  Result: {'ALL OK' if ok else 'SOME FAILURES'}")
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
