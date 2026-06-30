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

/* Stub for susfs_add_sus_path_loop - not in kernel-4.19 */
int susfs_add_sus_path_loop(void __user *arg)
{
    pr_info("susfs: susfs_add_sus_path_loop stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_add_sus_path_loop);

/* Stub for susfs_set_hide_sus_mnts_for_non_su_procs - not in kernel-4.19 */
int susfs_set_hide_sus_mnts_for_non_su_procs(void __user *arg)
{
    pr_info("susfs: susfs_set_hide_sus_mnts_for_non_su_procs stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_set_hide_sus_mnts_for_non_su_procs);

/* Stub for susfs_add_sus_map - not in kernel-4.19 */
int susfs_add_sus_map(void __user *arg)
{
    pr_info("susfs: susfs_add_sus_map stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_add_sus_map);

/* Stub for susfs_set_avc_log_spoofing - not in kernel-4.19 */
int susfs_set_avc_log_spoofing(void __user *arg)
{
    pr_info("susfs: susfs_set_avc_log_spoofing stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_set_avc_log_spoofing);

/* Stub for susfs_enable_log - not in kernel-4.19 */
int susfs_enable_log(void __user *arg)
{
    pr_info("susfs: susfs_enable_log stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_enable_log);

/* Stub for susfs_get_enabled_features - not in kernel-4.19 */
int susfs_get_enabled_features(void __user *arg)
{
    pr_info("susfs: susfs_get_enabled_features stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_get_enabled_features);

/* Stub for susfs_show_variant - not in kernel-4.19 */
int susfs_show_variant(void __user *arg)
{
    pr_info("susfs: susfs_show_variant stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_show_variant);

/* Stub for susfs_show_version - not in kernel-4.19 */
int susfs_show_version(void __user *arg)
{
    pr_info("susfs: susfs_show_version stub (no-op)\n");
    return 0;
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

/* Stub for susfs_is_current_proc_umounted - not in kernel-4.19 */
bool susfs_is_current_proc_umounted(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_proc_umounted);

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

/* Module initialization */
static int __init susfs_stubs_init(void)
{
    pr_info("susfs: stubs module loaded\n");
    return 0;
}

static void __exit susfs_stubs_exit(void)
{
    pr_info("susfs: stubs module unloaded\n");
}

module_init(susfs_stubs_init);
module_exit(susfs_stubs_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("SUSFS stub implementations for missing symbols");
MODULE_AUTHOR("SUSFS");
