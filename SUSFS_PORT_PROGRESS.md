# SUSFS v1.5.5 → v2.2.0 移植进度与计划

> 基线: simonpunk/susfs4ksu `kernel-4.19` (v1.5.5)
> 目标: simonpunk/susfs4ksu `gki-android14-6.1` (v2.2.0)
> 平台: OnePlus 8T (kebab), kernel 4.19.304, KSU-Next legacy
> **最后更新: 2026-07-03** | 已完成 v2.2.0 源码全量对比审计

---

## 一、整体进度（审计确认）

| 分类 | 已完成 | 说明 |
|------|--------|------|
| Kconfig 选项 | 17/17 编译启用 | ksu.config 全部 `=y`，GHA 额外注册 HAS_MAGIC_MOUNT(n) 共 18 个 |
| Dispatch 条目 | **16/20**（IOCTL + reboot 两处均已添加） | 4 个跳过（GKI only） |
| v1.5.5 原生功能 | 13/13 保留 | 全部无需修改 |
| v2.2.0 新增功能（非 GKI） | **16/16** 已移植 | 全部完成，sdcard 监听已移植 |
| GKI only 功能 | 有意跳过（4 个） | SHOW_SUS_SU_WORKING_MODE / IS_SUS_SU_READY / SUS_SU / ADD_SUS_KSTAT_STATICALLY |
| open_redirect 增强 | **8/8** 完成 | 5 spoof 函数 + UID_SCHEME + 增强 add + spoof_show_map_vma |
| stub 签名修复 | **8/8** 已修正 | commit `f3e205f` |
| 刷机验证 | 内核正常启动，16 功能注册 | 运行时 IOCTL 待 APK |

---

## 二、v2.2.0 功能移植详细状态

### ✅ v1.5.5 原生（全部保留，共 13 个）

SUS_PATH / SUS_MOUNT / SUS_KSTAT / UPDATE_SUS_KSTAT / TRY_UMOUNT / SPOOF_UNAME / SPOOF_CMDLINE / OPEN_REDIRECT / ENABLE_LOG / HIDE_SYMS / AUTO_ADD_SUS_BIND_MOUNT / AUTO_ADD_SUS_KSU_DEFAULT_MOUNT / AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT

### ✅ v2.2.0 新增（已移植 14 个）

| 功能 | 注入脚本 | 新增函数数 | 验证 |
|------|----------|-----------|------|
| SUS_MAP（/proc/pid/maps 隐藏） | `inject-susfs-sus-map.py` | 1 | features 显示 |
| AVC_LOG_SPOOFING（SELinux avc 伪造） | `inject-v2-features-batch1.py` | 1 | features 显示 |
| SUS_PATH_LOOP（路径循环防检测） | `inject-v2-features-batch2.py` | 1 | 编译/注入确认 |
| HIDE_SUS_MNTS（非 root 隐藏挂载） | `inject-v2-features-batch2.py` | 1 | 编译/注入确认 |
| fillattr spoofer（OVERLAYFS kstat） | `inject-v2-features-batch2.py` | 1 | 编译/注入确认 |
| show_map_vma spoofer（maps 增强） | `inject-v2-features-batch2.py` | 1 | 编译/注入确认 |
| open_redirect 增强（VFS 钩子） | `inject-open-redirect-enhanced.py` | 5 | 启动+编译 |
| open_redirect spoof_show_map_vma | `inject-open-redirect-enhanced.py` step4 | 1 | task_mmu.c `show_map_vma` redirect 路径伪造 |
| UID_SCHEME + KSTAT spoof 位扩展 | `inject-open-redirect-enhanced.py` | 0（结构扩展） | 编译 |
| get_enabled_features 真实实现 | dispatch 内联 | 1 | `ksud susfs features` |
| show_version/variant err 字段 | dispatch 内联 | 0（结构对齐） | 静态分析 |
| stub 签名修正 | `susfs_stubs.c` 修改 | 0 | 静态分析 |

### ❌ sdcard 监听（已于 2026-07-07 完成移植）

| 函数 | 当前状态 | 工作量 | 风险 |
|------|---------|--------|------|
| `susfs_start_sdcard_monitor_fn` | ✅ 4.19 适配移植 | ~4h | 🟡 中（fsnotify API 差异） |
| `susfs_sdcard_cleanup_fn` | ✅ 已实现 | 同上 | 🟢 低 |
| `susfs_handle_sdcard_event` | ✅ 用 handle_event 替代 handle_inode_event | 同上 | 🟡 中（4.19 回调签名差异） |
| `watch_one_dir` + `add_mark_on_inode` | ✅ 已实现 | 同上 | 🟢 低 |

> 移植说明：
> - 4.19 无 `handle_inode_event`（5.1+），改用 `handle_event`，`file_name` 为 `const unsigned char *`
> - 代替 `setup_selinux()` 使用 `override_creds(ksu_cred)`（跨模块兼容）
> - 通过 `late_initcall` 自动启动，不依赖 KSU 初始化顺序
> - 旧 stub 已移除，由 `kernel-patches/feature/susfs_sdcard_monitor.c` 提供真实实现

### ⏭️ GKI only（有意跳过，非 4.19 平台）

- `CMD_SUSFS_SHOW_SUS_SU_WORKING_MODE`
- `CMD_SUSFS_IS_SUS_SU_READY`
- `CMD_SUSFS_SUS_SU`
- `CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY`（无 v1.5.5 对应函数）

---

## 三、刷机验证结果

执行 `fastboot boot` 临时启动 CI 构建的 `ksu-debug-boot.img`，已确认：

**编译+启动 ✅**
- GHA 构建 0 错误，ANDROID! 魔数正确，DTB 525173 bytes 正确追加
- 设备 ADB 重连 < 5s，PMIC 关机原因为 PS_HOLD（正常）
- dmesg 中 0 条 panic/BUG/Oops

**用户态通信 ✅**
- `ksud susfs support` → Supported
- `ksud susfs version` → v2.2.0
- `ksud susfs variant` → NON-GKI
- `ksud susfs features` → 全部 16 个功能
- `ksud debug version` → 33188
- `ksud feature check avc_spoof` → supported

**符号隐藏 ✅**
- `kallsyms` 中 `ksu_handle*` 0 个
- `kallsyms` 中 `susfs_init`/`susfs_add_*` 0 个
- stub `EXPORT_SYMBOL` 元数据因 `__` 前缀绕过过滤器，不影响功能

**运行时功能验证 ⏳**
11 项功能（SUS_PATH / SUS_MOUNT / SUS_KSTAT / SPOOF_UNAME / SPOOF_CMDLINE / OPEN_REDIRECT / SUS_MAP / AVC_LOG_SPOOFING / ENABLE_LOG / TRY_UMOUNT / SUS_PATH_LOOP）需通过 KernelSU 管理器 APK 调用 IOCTL 验证，当前未完成。

---

## 四、当前阻塞问题

| 问题 | 根因 | 状态 |
|------|------|------|
| Superuser 页面 | libsu v6.0.0 的 AAR 在 JitPack 为空 → 降级 5.3.0 修复 | ⏳ APK 构建正常，待安装验证 |
| UAPI 版本不匹配 | legacy 分支无 `KERNEL_SU_UAPI_VERSION=2` | ✅ 已修复 |
| SUSFS clone 网络失败 | gitlab.com 对 GHA runner 不稳定 | ✅ 已修复（3 次重试） |
| selinux_hide 未移植 | 缺 patch_memory/lsm_hook/symbol_resolver 基础设施 | 📄 文档就绪，待执行 |

---

## 五、未完成功能

| 功能 | 优先级 | 工作量 | 说明 |
|------|--------|--------|------|
| sdcard 监听 | 🟢 低 | 🔴 高 | fsnotify + kthread，v1.5.5 也没有此功能 |
| selinux_hide | 🟡 中 | 🟡 中 | 需移植 3 个基础设施文件，有文档 |
| 运行时功能 APK 验证 | 🔴 高 | 🟢 低 | 安装 APK 后逐一验证 11 项 IOCTL 功能 |

---

## 六、附录：CMD 常量对照

| CMD | 值 | v1.5.5 | v2.2.0 | Dispatch | 状态 |
|-----|-----|:------:|:------:|:--------:|------|
| `CMD_SUSFS_ADD_SUS_PATH` | 0x55550 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_ADD_SUS_MOUNT` | 0x55560 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_ADD_SUS_PATH_LOOP` | 0x55553 | ❌ | ✅ | ✅ | ✅ 已移植 |
| `CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS` | 0x55561 | ❌ | ✅ | ✅ | ✅ 已移植 |
| `CMD_SUSFS_ADD_SUS_KSTAT` | 0x55570 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_UPDATE_SUS_KSTAT` | 0x55571 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY` | 0x55572 | ❌ | ✅ | ❌ | ⏭️ 无 v1.5.5 实现 |
| `CMD_SUSFS_ADD_TRY_UMOUNT` | 0x55580 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_SET_UNAME` | 0x55590 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_ENABLE_LOG` | 0x555a0 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG` | 0x555b0 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_ADD_OPEN_REDIRECT` | 0x555c0 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_SHOW_VERSION` | 0x555e1 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_SHOW_ENABLED_FEATURES` | 0x555e2 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_SHOW_VARIANT` | 0x555e3 | ✅ | ✅ | ✅ | 原生 |
| `CMD_SUSFS_SHOW_SUS_SU_WORKING_MODE` | 0x555e4 | ✅ | ✅ | ❌ | ⏭️ GKI only |
| `CMD_SUSFS_IS_SUS_SU_READY` | 0x555f0 | ✅ | ✅ | ❌ | ⏭️ GKI only |
| `CMD_SUSFS_SUS_SU` | 0x60000 | ✅ | ✅ | ❌ | ⏭️ GKI only |
| `CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING` | 0x60010 | ❌ | ✅ | ✅ | ✅ 已移植 |
| `CMD_SUSFS_ADD_SUS_MAP` | 0x60020 | ❌ | ✅ | ✅ | ✅ 已移植 |

---

## 七、附录：susfs_stubs.c 函数状态（全部已修正 ✅）

共 **29 个函数**，其中：
- 全局（无条件）：1 个（`__strncpy_from_user_nofault` — 4.19 兼容）
- `#ifndef CONFIG_KSU_SUSFS` 内：21 个（CONFIG=n 时提供符号）
- always-needed 段：7 个（`susfs_is_current_proc_umounted[_app]`, `susfs_get_redirected_path`, `susfs_is_current_ksu_domain`, `susfs_is_current_zygote_domain`, `ksu_try_umount`, `susfs_try_umount_all`）

>`__strncpy_from_user_nofault` 和 `ipa_stack_to_dts` 是编译兼容辅助函数，非 SUSFS 功能符号，PORT_PROGRESS 之前未计入。

全部 8 个 dispatch 调用的 stub 签名已从旧的 `int(void*)` 修正为 `void(void**)`，与 v2.2.0 一致（commit `f3e205f`）。
