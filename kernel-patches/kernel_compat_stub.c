// SPDX-License-Identifier: GPL-2.0
/*
 * kernel_compat_stub.c - Kernel 4.19 compatibility stubs
 *
 * SukiSU-Ultra uses some kernel internal functions that are not available
 * in kernel 4.19. This file provides stub implementations.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/errno.h>

int path_mount(const char *dev_name, struct path *path, const char *type_page,
               unsigned long flags, void *data_page)
{
    pr_info("ksu: path_mount stub (kernel 4.19)\n");
    return -EOPNOTSUPP;
}

int path_umount(struct path *path, int flags)
{
    pr_info("ksu: path_umount stub (kernel 4.19)\n");
    return -EOPNOTSUPP;
}

void seccomp_filter_release(struct task_struct *tsk, int flags)
{
    pr_info("ksu: seccomp_filter_release stub (kernel 4.19)\n");
}
