// SPDX-License-Identifier: GPL-2.0-only
/*
 * susfs_stubs.c - SUSFS compatibility stubs for builtin branch
 *
 * The dispatch code calls newer SUSFS APIs that don't exist in the
 * kernel-4.19 SUSFS branch. These stubs provide missing symbols.
 * The ld.lld --allow-multiple-definition wrapper handles duplicates.
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

#ifndef CONFIG_KSU_SUSFS
void susfs_add_sus_path_loop(void __user **user_info)
{
}
EXPORT_SYMBOL(susfs_add_sus_path_loop);

void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info)
{
}
EXPORT_SYMBOL(susfs_set_hide_sus_mnts_for_non_su_procs);

void susfs_add_sus_map(void __user **user_info)
{
}
EXPORT_SYMBOL(susfs_add_sus_map);

void susfs_set_avc_log_spoofing(void __user **user_info)
{
}
EXPORT_SYMBOL(susfs_set_avc_log_spoofing);

void susfs_enable_log(void __user **user_info)
{
}
EXPORT_SYMBOL(susfs_enable_log);

void susfs_get_enabled_features(void __user **user_info)
{
    char empty = 0;
    copy_to_user(*user_info, &empty, 1);
}
EXPORT_SYMBOL(susfs_get_enabled_features);

void susfs_show_variant(void __user **user_info)
{
    char buf[] = "NON-GKI";
    copy_to_user(*user_info, buf, sizeof(buf));
}
EXPORT_SYMBOL(susfs_show_variant);

void susfs_show_version(void __user **user_info)
{
    char buf[] = "v0.0.0";
    copy_to_user(*user_info, buf, sizeof(buf));
}
EXPORT_SYMBOL(susfs_show_version);

bool susfs_starts_with(const char *str, const char *prefix)
{
    return strncmp(str, prefix, strlen(prefix)) == 0;
}
EXPORT_SYMBOL(susfs_starts_with);

bool susfs_ends_with(const char *str, const char *suffix)
{
    size_t str_len = strlen(str);
    size_t suffix_len = strlen(suffix);
    if (suffix_len > str_len)
        return false;
    return strcmp(str + str_len - suffix_len, suffix) == 0;
}
EXPORT_SYMBOL(susfs_ends_with);

bool susfs_is_inode_sus_path(struct inode *inode)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_inode_sus_path);

void susfs_mark_inode_sus_kstat(struct inode *inode)
{
}
EXPORT_SYMBOL(susfs_mark_inode_sus_kstat);

void susfs_set_current_proc_umounted(void)
{
}
EXPORT_SYMBOL(susfs_set_current_proc_umounted);

int susfs_start_sdcard_monitor_fn(void)
{
    return 0;
}
EXPORT_SYMBOL(susfs_start_sdcard_monitor_fn);

void ksu_selinux_hide_handle_post_fs_data(void)
{
}
EXPORT_SYMBOL(ksu_selinux_hide_handle_post_fs_data);

void ksu_selinux_hide_handle_second_stage(void)
{
}
EXPORT_SYMBOL(ksu_selinux_hide_handle_second_stage);

long strncpy_from_user_nofault(char *dst, const void __user *unsafe_addr, long count)
{
    return __strncpy_from_user_nofault(dst, unsafe_addr, count);
}
EXPORT_SYMBOL(strncpy_from_user_nofault);

bool susfs_is_allow_su(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_allow_su);

int ksu_escape_to_root(void)
{
    return 0;
}
EXPORT_SYMBOL(ksu_escape_to_root);

void susfs_extra_works(void)
{
}
EXPORT_SYMBOL(susfs_extra_works);

void ipa_stack_to_dts(void)
{
}
EXPORT_SYMBOL(ipa_stack_to_dts);

#endif /* !CONFIG_KSU_SUSFS */

/*
 * Always-compiled stubs for symbols referenced by SUSFS v2.2.0 enhacements
 * or the 50_add patch that may not be present in all SUSFS source files.
 */
bool susfs_is_current_proc_umounted_app(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_proc_umounted_app);

bool susfs_is_current_proc_umounted(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_proc_umounted);

char *susfs_get_redirected_path(struct inode *inode)
{
    return NULL;
}
EXPORT_SYMBOL(susfs_get_redirected_path);

bool susfs_is_current_ksu_domain(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_ksu_domain);

bool susfs_is_current_zygote_domain(void)
{
    return false;
}
EXPORT_SYMBOL(susfs_is_current_zygote_domain);

void ksu_try_umount(const char *mnt, bool check_mnt, int flags, uid_t uid)
{
}
EXPORT_SYMBOL(ksu_try_umount);

void susfs_try_umount_all(uid_t uid)
{
}
EXPORT_SYMBOL(susfs_try_umount_all);
