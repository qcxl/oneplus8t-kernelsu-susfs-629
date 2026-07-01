# SUSFS v1.5.5 → v2.2.0 移植进度与差异对比

> 基于实际代码对比，非猜测
> 基线: simonpunk/susfs4ksu kernel-4.19 (v1.5.5, 916 行)
> 目标: sidex15/android_kernel_lge_sm8150 OpenELA-4.14.y-susfs (v2.2.0, 1516 行)
> 差异: +600 行
> **最后更新: 2026-07-01**

---

## 一、整体进度

| 维度 | v1.5.5 | v2.2.0 | 已移植 | 待移植 |
|------|--------|--------|--------|--------|
| susfs.c 行数 | 916 | 1516 | ~400 行（inject 脚本注入） | ~200 行 |
| Kconfig 选项 | 16 个 | 19 个 | 16/16 编译 | 0 |
| dispatch CMD | 15 个 | 19 个 | 15/19 | 4 个 |
| 功能函数 | 25 个 | 50+ 个 | ~20 个新增 | ~10 个 |

---

## 二、v2.2.0 独有功能移植状态

### P0：核心功能（全部完成 ✅）

| 功能 | 说明 | 新增函数 | 工作量 | 状态 | 验证方式 |
|------|------|----------|--------|------|---------|
| **sus_map** | 隐藏 `/proc/pid/maps` 条目 | `susfs_add_sus_map` | 低 | ✅ **已完成** | 调用返回 `ret: 0`，非 stub |
| **AVC log spoofing** | 伪造 SELinux avc 审计日志 | `susfs_set_avc_log_spoofing` | 低 | ✅ **已完成** | 调用返回 `ret: 0`，非 stub |

### P1：功能完善（大部分完成）

| 功能 | 说明 | 新增函数 | 工作量 | 状态 |
|------|------|----------|--------|------|
| **sus_path_loop** | 路径循环检测 | `susfs_add_sus_path_loop` | 中 | ✅ **已完成**（返回 `ret: -22` 真实实现） |
| **kstat 哈希表化** | 改进 stat 伪造性能 | `susfs_generic_fillattr_spoofer` | 中 | ✅ **已验证**（GHA 日志 + 本地测试确认注入编译，spoofer 对 root 跳过属正常设计） |
| **show_map_vma_spoofer** | maps 伪造增强 | `susfs_show_map_vma_spoofer` | 中 | ✅ **已验证**（同上） |
| **hide_mnts** | 非 root 进程隐藏挂载 | `susfs_set_hide_sus_mnts_for_non_su_procs` | 中 | ✅ **已完成**（返回 `ret: 0`，非 stub） |
| **用户态通信** | features/variant/version 查询 | dispatch 内联实现 | 低 | ✅ **已完成**（version 返回 v2.2.0） |

### P2：可选增强（未开始）

| 功能 | 说明 | 新增函数 | 工作量 | 状态 |
|------|------|----------|--------|------|
| **open_redirect 增强** | 更多路径重定向函数 | `spoof_do_sys_openat`, `spoof_readlink`, `spoof_statfs` 等 7 个 | 中 | ❌ 未开始 |
| **sdcard 监听** | 监听解密后 sdcard 事件 | `susfs_start_sdcard_monitor_fn` 等 4 个 | 高 | ❌ 未开始 |
| **is_inode_sus_path** | 检查 inode 是否在 sus_path 中 | `susfs_is_inode_sus_path` | 低 | ❌ 未开始 |
| **mark_inode_kstat** | 标记 inode 的 kstat | `susfs_mark_inode_sus_kstat` | 低 | ❌ 未开始 |
| **cmdline/bootconfig spoof 增强** | — | — | 低 | ❌ 未开始 |
| **sus_su 废弃** | 旧版 sus_su 相关（GKI only） | — | — | ⏭️ 跳过（4.19 不支持） |

---

## 三、函数级对比

### 3.1 v1.5.5 已有且保留的函数（25 个，无需改动）

全部保留，无需改动。

### 3.2 v2.2.0 新增函数（30+ 个）

| 分类 | 函数 | 状态 |
|------|------|------|
| **sus_map** | `susfs_add_sus_map` | ✅ 注入+验证 |
| **AVC log spoofing** | `susfs_set_avc_log_spoofing` | ✅ 注入+验证 |
| **sus_path_loop** | `susfs_add_sus_path_loop`, `susfs_run_sus_path_loop` | ✅ 注入+验证 |
| **hide_mnts** | `susfs_set_hide_sus_mnts_for_non_su_procs` | ✅ 注入+验证 |
| **kstat 增强** | `susfs_generic_fillattr_spoofer`, `susfs_show_map_vma_spoofer` | ✅ CMD 处理 + dmesg + GHA 日志三重确认 |
| **用户态通信** | `susfs_get_enabled_features`, `susfs_show_variant`, `susfs_show_version` | ✅ dispatch 内联实现（非 stub） |
| **open_redirect 增强** | 7 个函数 | ❌ 未开始 |
| **sdcard 监控** | 4 个函数 | ❌ 未开始 |
| **工具函数** | `susfs_starts_with`, `copy_config_to_buf` | ✅ 源码中有真实实现（位于 `#ifndef` 块内，当前 SUSFS=y 未编译） |

---

## 四、CMD 常量状态

| CMD | 值 | v1.5.5 | v2.2.0 | dispatch | 说明 |
|-----|-----|:----:|:----:|:--------:|------|
| `CMD_SUSFS_ADD_SUS_PATH` | 0x55550 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_ADD_SUS_MOUNT` | 0x55560 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_ADD_SUS_PATH_LOOP` | 0x55553 | ❌ | ✅ | ✅ | ✅ 已移植 |
| `CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS` | 0x55561 | ❌ | ✅ | ✅ | ✅ 已移植 |
| `CMD_SUSFS_ADD_SUS_KSTAT` | 0x55570 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_UPDATE_SUS_KSTAT` | 0x55571 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY` | 0x55572 | ✅ | ✅ | ✅ | 已补全 |
| `CMD_SUSFS_ADD_TRY_UMOUNT` | 0x55580 | ✅ | ✅ | ✅ | 已补全 |
| `CMD_SUSFS_SET_UNAME` | 0x55590 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_ENABLE_LOG` | 0x555a0 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG` | 0x555b0 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_ADD_OPEN_REDIRECT` | 0x555c0 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_RUN_UMOUNT_FOR_CURRENT_MNT_NS` | 0x555d0 | ✅ | ❌ | ❌ | v1.5.5 独有，跳过 |
| `CMD_SUSFS_SHOW_VERSION` | 0x555e1 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_SHOW_ENABLED_FEATURES` | 0x555e2 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_SHOW_VARIANT` | 0x555e3 | ✅ | ✅ | ✅ | |
| `CMD_SUSFS_SHOW_SUS_SU_WORKING_MODE` | 0x555e4 | ✅ | ✅ | ❌ | GKI only |
| `CMD_SUSFS_IS_SUS_SU_READY` | 0x555f0 | ✅ | ✅ | ❌ | GKI only |
| `CMD_SUSFS_SUS_SU` | 0x60000 | ✅ | ✅ | ❌ | GKI only |
| `CMD_SUSFS_ADD_SUS_MAP` | 0x60020 | ❌ | ✅ | ✅ | ✅ 已移植 |
| `CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING` | 0x60010 | ❌ | ✅ | ✅ | ✅ 已移植 |

---

## 五、已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| `ksud susfs features` 仅显示 SUS_PATH | 🟡 已修复？ | 字符串长度已修正，待 GHA 构建确认 |
| KSU Manager App Superuser 页面转圈 | ❌ 未修复 | App 自身 `RootServerMain` ClassNotFoundException |
| stub 覆盖真实实现 | ✅ 已修复 | `#ifndef CONFIG_KSU_SUSFS` 分离 stub |

---

## 六、剩余工作优先级

### 第一轮（P0 — 全部完成 ✅）

| 特性 | 状态 |
|------|------|
| **AVC log spoofing** | ✅ |
| **sus_path_loop** | ✅ |
| **hide_mnts** | ✅ |
| **sus_map** | ✅ |
| dispatch features/variant/version | ✅ |

### 第二轮（P1 — 可做但不紧急）

| 特性 | 预计工作量 | 说明 |
|------|-----------|------|
| kstat 哈希表化 + show_map_vma spoofer | — | ✅ **已完成** |
| 补齐遗漏的 CMD dispatch 条目 | — | ✅ **已完成**（ADD_SUS_KSTAT_STATICALLY + ADD_TRY_UMOUNT 已补；SUS_SU 系列 GKI only 跳过） |
| open_redirect 增强 | 1-2 天 | 7 个新函数，涉及多个 VFS 文件 |

### 第三轮（P2 — 可选）

| 特性 | 预计工作量 | 说明 |
|------|-----------|------|
| sdcard 监听 | 2-3 天 | 复杂的 inotify 监听逻辑 |
| 小型辅助函数 | 0.5 天 | is_inode_sus_path, mark_inode_sus_kstat 等 |
