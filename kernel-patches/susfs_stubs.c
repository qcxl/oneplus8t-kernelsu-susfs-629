// SPDX-License-Identifier: GPL-2.0-only
/*
 * susfs_stubs.c - SUSFS compatibility stubs for kernel-4.19 branch
 *
 * SukiSU-Ultra builtin branch dispatch.c calls newer SUSFS APIs
 * that don't exist in the kernel-4.19 branch. These stubs provide
 * the missing symbols so the kernel can compile and link.
 * The stubs return success without performing any operation,
 * which is safe for features not available in kernel-4.19.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/string.h>
#include <linux/device.h>
#include <linux/susfs.h>

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

/* Stub for susfs_add_sus_kstat (static inline version in newer SUSFS) */
int susfs_add_sus_kstat(struct st_susfs_sus_kstat __user *user_info)
{
    pr_info("susfs: susfs_add_sus_kstat stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_add_sus_kstat);

/* Stub for susfs_update_sus_kstat (static inline version in newer SUSFS) */
int susfs_update_sus_kstat(struct st_susfs_sus_kstat __user *user_info)
{
    pr_info("susfs: susfs_update_sus_kstat stub (no-op)\n");
    return 0;
}
EXPORT_SYMBOL(susfs_update_sus_kstat);

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

/* Stub for ipa_stack_to_dts - may be missing in some kernel configs */
void ipa_stack_to_dts(void)
{
    pr_info("susfs: ipa_stack_to_dts stub called\n");
}
EXPORT_SYMBOL(ipa_stack_to_dts);

/* Stub for fsa4480 functions - may be missing in some kernel configs */
int fsa4480_reg_notifier(struct device *dev)
{
    pr_info("susfs: fsa4480_reg_notifier stub called\n");
    return 0;
}
EXPORT_SYMBOL(fsa4480_reg_notifier);

void fsa4480_unreg_notifier(struct device *dev)
{
    pr_info("susfs: fsa4480_unreg_notifier stub called\n");
}
EXPORT_SYMBOL(fsa4480_unreg_notifier);

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
