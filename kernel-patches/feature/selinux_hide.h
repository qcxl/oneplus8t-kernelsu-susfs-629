#ifndef __KSU_H_SELINUX_HIDE
#define __KSU_H_SELINUX_HIDE

/* 4.19 完整版 selinux_hide — 移植自 KernelSU-Next dev 分支
 *
 * 提供 4 个 SELinux 隐藏钩子：
 *   1. fake status page (来自 legacy 分支 commit 77b30272，保留复用)
 *   2. context_write   (新增，过滤模式)
 *   3. access_write    (新增，过滤模式)
 *   4. setprocattr     (来自 inject-selinux-hide.py，合并)
 *
 * 入口函数（init.c 调用）:
 *   ksu_selinux_hide_init()                    — 注册 feature handler
 *   ksu_selinux_hide_exit()                    — 清理
 *   ksu_selinux_hide_handle_second_stage()     — 第二阶段初始化（fake status）
 *   ksu_selinux_hide_handle_post_fs_data()     — post-fs-data 完成
 *
 * Feature ID: KSU_FEATURE_SELINUX_HIDE (=4)
 */

void ksu_selinux_hide_init(void);
void ksu_selinux_hide_exit(void);
void ksu_selinux_hide_handle_second_stage(void);
void ksu_selinux_hide_handle_post_fs_data(void);

#endif /* __KSU_H_SELINUX_HIDE */
