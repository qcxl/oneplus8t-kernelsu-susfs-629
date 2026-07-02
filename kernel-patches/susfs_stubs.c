// SPDX-License-Identifier: GPL-2.0-only
/*
 * susfs_stubs.c - SUSFS compatibility stubs for builtin branch
 *
 * SukiSU-Ultra builtin branch dispatch.c calls newer SUSFS APIs
 * that don't exist in the kernel-4.19 SUSFS branch.
 * These stubs provide the missing symbols so the kernel can link.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/string.h>
#include <linux/device.h>
#include <linux/types.h>
#include <linux/uaccess.h>

/* Declare __strncpy_from_user_nofault if not available in headers */
long __strncpy_from_user_nofault(char *dst, const void __user *unsafe_addr, long count)
{
    return -EFAULT;
}
EXPORT_SYMBOL(__strncpy_from_user_nofault);

/* All SUSFS function stubs below are ONLY used when CONFIG_KSU_SUSFS is disabled.
   When CONFIG_KSU_SUSFS=y, the real implementations in fs/susfs.c take precedence,
   and these stubs are excluded to avoid --allow-multiple-definition picking the stub. */
#ifndef CONFIG_KSU_SUSFS
void susfs_add_sus_path_loop(void __user **user_info)
{
    /* stub: v2.2.0 dispatch passes void**, no-op when SUSFS disabled */
}
EXPORT_SYMBOL(susfs_add_sus_path_loop);

void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info)
{
    /* stub */
}
EXPORT_SYMBOL(susfs_set_hide_sus_mnts_for_non_su_procs);

void susfs_add_sus_map(void __user **user_info)
{
    /* stub */
}
EXPORT_SYMBOL(susfs_add_sus_map);

void susfs_set_avc_log_spoofing(void __user **user_info)
{
    /* stub */
}
EXPORT_SYMBOL(susfs_set_avc_log_spoofing);

void susfs_enable_log(void __user **user_info)
{
    /* stub */
}
EXPORT_SYMBOL(susfs_enable_log);

void susfs_get_enabled_features(void __user **user_info)
{
    /* stub: no SUSFS features enabled */
    char empty = 0;
    copy_to_user(*user_info, &empty, 1);
}
EXPORT_SYMBOL(susfs_get_enabled_features);

void susfs_show_variant(void __user **user_info)
{
    /* stub: return "NON-GKI" variant */
    char buf[] = "NON-GKI";
    copy_to_user(*user_info, buf, sizeof(buf));
}
EXPORT_SYMBOL(susfs_show_variant);

void susfs_show_version(void __user **user_info)
{
    /* stub: return disabled version */
    char buf[] = "v0.0.0";
    copy_to_user(*user_info, buf, sizeof(buf));
}
EXPORT_SYMBOL(susfs_show_version);

/* Stub for susfs_starts_with - not in kernel-4.19 */
bool susfs_starts_with(const char *str, const char *prefix)
{
    return strncmp(str, prefix, strlen(prefix)) == 0;
}
EXPORT_SYMBOL(susfs_starts_with);

/* Stub for susfs_ends_with - not in kernel-4.19 */
bool susfs_ends_with(const char *str, const char *suffix)
{
    size_t str_len = strlen(str);
    size_t suffix_len = strlen(suffix);
    if (suffix_len > str_len)
        return false;
    return strcmp(str + str_len - suffix_len, suffix) == 0;
}
EXPORT_SYMBOL(susfs_ends_with);

/* Helper: check if inode is in sus_path list — always false when SUSFS disabled */
bool susfs_is_inode_sus_path(struct inode *inode)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_inode_sus_path);

/* Helper: mark inode for kstat spoofing — no-op when SUSFS disabled */
void susfs_mark_inode_sus_kstat(struct inode *inode)
{
}
EXPORT_SYMBOL(susfs_mark_inode_sus_kstat);

/* Stub for susfs_set_current_proc_umounted - not in kernel-4.19 */
void susfs_set_current_proc_umounted(void)
{
    pr_info("susfs: susfs_set_current_proc_umounted stub (no-op)\n");
}
EXPORT_SYMBOL(susfs_set_current_proc_umounted);

/* Stub for susfs_start_sdcard_monitor_fn - not in kernel-4.19 */
int susfs_start_sdcard_monitor_fn(void)
{
    pr_info("susfs: susfs_start_sdcard_monitor_fn stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_start_sdcard_monitor_fn);

/* Stub for ksu_selinux_hide_handle_post_fs_data - may be missing */
void ksu_selinux_hide_handle_post_fs_data(void)
{
    pr_info("susfs: ksu_selinux_hide_handle_post_fs_data stub (no-op)\n");
}
EXPORT_SYMBOL(ksu_selinux_hide_handle_post_fs_data);

/* Stub for ksu_selinux_hide_handle_second_stage - may be missing */
void ksu_selinux_hide_handle_second_stage(void)
{
    pr_info("susfs: ksu_selinux_hide_handle_second_stage stub (no-op)\n");
}
EXPORT_SYMBOL(ksu_selinux_hide_handle_second_stage);

/* Stub for strncpy_from_user_nofault - wrapper for __strncpy_from_user_nofault */
long strncpy_from_user_nofault(char *dst, const void __user *unsafe_addr, long count)
{
    return __strncpy_from_user_nofault(dst, unsafe_addr, count);
}
EXPORT_SYMBOL(strncpy_from_user_nofault);

/* Stub for susfs_is_allow_su - not in kernel-4.19 */
bool susfs_is_allow_su(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_allow_su);

/* Stub for ksu_escape_to_root - not in kernel-4.19 */
int ksu_escape_to_root(void)
{
    pr_info("susfs: ksu_escape_to_root stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(ksu_escape_to_root);

/* Stub for susfs_extra_works - not in kernel-4.19 */
void susfs_extra_works(void)
{
    pr_info("susfs: susfs_extra_works stub (no-op)\n");
}
EXPORT_SYMBOL(susfs_extra_works);

/* Stub for ipa_stack_to_dts - may be missing in some kernel configs */
void ipa_stack_to_dts(void)
{
    pr_info("susfs: ipa_stack_to_dts stub called\n");
}
EXPORT_SYMBOL(ipa_stack_to_dts);

#endif /* !CONFIG_KSU_SUSFS */

/* Stub for susfs_is_current_proc_umounted_app - v2.2.0 new, always needed
   because open_redirect spoof code references it even when SUSFS=y. */
bool susfs_is_current_proc_umounted_app(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_proc_umounted_app);

/* Stub for susfs_is_current_proc_umounted - always needed when SUSFS=y
   because it may not be in v1.5.5 sus_su.c from gitlab. */
bool susfs_is_current_proc_umounted(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_proc_umounted);

/* Stub for susfs_get_redirected_path - was in old open_redirect section
   of susfs.c (v1.5.5), which was removed and replaced by enhanced version. */
char *susfs_get_redirected_path(struct inode *inode)
{
    return NULL;
}
EXPORT_SYMBOL(susfs_get_redirected_path);

/* The following stubs are always needed (no real implementations exist):
   - susfs_is_current_ksu_domain, susfs_is_current_zygote_domain
   - ksu_try_umount, susfs_try_umount_all
   These are referenced by the KSU dispatch code but defined in the 50_add
   patch which may not apply cleanly on all kernel versions. */

/* Stub for susfs_is_current_ksu_domain - defined in 10_enable patch */
bool susfs_is_current_ksu_domain(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_ksu_domain);

/* Stub for susfs_is_current_zygote_domain - defined in 10_enable patch */
bool susfs_is_current_zygote_domain(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_zygote_domain);

/* Stub for ksu_try_umount - defined in 10_enable patch */
void ksu_try_umount(const char *mnt, bool check_mnt, int flags, uid_t uid)
{
    pr_info("susfs: ksu_try_umount stub (no-op)\n");
}
EXPORT_SYMBOL(ksu_try_umount);

/* Stub for susfs_try_umount_all - defined in 10_enable patch */
void susfs_try_umount_all(uid_t uid)
{
    pr_info("susfs: susfs_try_umount_all stub (no-op)\n");
}
EXPORT_SYMBOL(susfs_try_umount_all);

/* NOTE: No module_init/module_exit — this is compiled as obj-y (built-in),
   not as a module. module_init in built-in code is harmful: it registers a
   spurious initcall that serves no purpose since all real implementations
   come from fs/susfs.c (via inject scripts) or the 50_add patch. */
