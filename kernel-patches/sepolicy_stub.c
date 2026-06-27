// SPDX-License-Identifier: GPL-2.0
/*
 * sepolicy.c - Kernel 4.19 compatibility stubs
 *
 * SukiSU-Ultra's sepolicy.c uses kernel 5.x SELinux APIs not available in 4.19.
 * This file provides stub implementations for kernel 4.19.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/printk.h>

/* Kernel 4.19 requires explicit forward declaration */
struct selinux_state;

void ksu_apply_sepolicy(struct selinux_state *state)
{
    pr_info("ksu: ksu_apply_sepolicy stub (kernel 4.19)\n");
}

void ksu_reset_sepolicy(struct selinux_state *state)
{
    pr_info("ksu: ksu_reset_sepolicy stub (kernel 4.19)\n");
}

void handle_sepolicy(struct selinux_state *state)
{
    pr_info("ksu: handle_sepolicy stub (kernel 4.19)\n");
}
