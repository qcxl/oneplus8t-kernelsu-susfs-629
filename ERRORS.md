# 错误经验库

> `2.3.0` | 项目：SUSFS v1.5.5 → v2.2.0 port (KSUN-legacy)
> 每次修复后在此新增条目。通用经验加 `[cross-project]` 标签。

## E001：SYS_SECCOMP 阻止 KSU fd 安装导致设置页开关项缺失

**现象**：管理器 App 设置页的 KernelFeaturesCard 中，传统 SU 命令支持、内核处理卸载模块、SU 日志、ADB Root、Hide SELinux modification、AVC 日志伪装 共 6 个开关项不显示。logcat 出现 `F/DEBUG: signal 31 (SIGSYS) Cause: seccomp prevented call to disallowed arm64 system call 142`。

**根因**：管理器 App 嵌入的 `libksud.so` 在 `init_driver_fd()` 中先尝试 `scan_driver_fd()`（扫描 `/proc/self/fd` 寻找 `[ksu_driver]` 匿名 inode），失败后回退到 `syscall(SYS_reboot, KSU_INSTALL_MAGIC1, KSU_INSTALL_MAGIC2, 0, &fd)`。Android 的 seccomp 白名单不允许 `__NR_reboot=142`，导致 SIGSYS 杀进程。所有 KSU supercall 无法执行，`ksud feature check <feature>` 返回空字符串，UI 判断为 `unsupported` 隐藏开关。

**修复**：在 `supercall.c` 中添加 `secure_computing` kprobe。当捕获到 `__NR_reboot` 且参数为 KSU 魔数时，跳过 seccomp 检查（return 1）。另添加始终注册的 `__arm64_sys_reboot` kprobe（不依赖 `KSU_KPROBES_HOOK`），在绕过 seccomp 后安装 KSU driver fd 并返回 fd 号。

**教训**：
- 不能假设 Android 进程可以调用 `reboot` 等被 seccomp 限制的 syscall
- kprobe 在 `secure_computing` 上可以绕过 seccomp，且只影响极窄的条件（`__NR_reboot + 0xDEADBEEF + 0xCAFEBABE`）
- `PT_REGS_SYSCALL_PARM4` 在 arm64 arch.h 中有定义，不能用 `PT_REGS_PARM4`（未定义）

**锚点**：`drivers/kernelsu/supercall/supercall.c` — `seccomp_bypass_pre()` + `ksu_reboot_kprobe_pre()`

**标签**：cross-project

---

## E002：`__ksu_is_allow_uid_for_current(0)` 返回 `is_ksu_domain()` 导致 adb root 下 grant_root 被拒

**现象**：冷启动后 `ksud debug su` 返回 `Error: Operation not permitted (os error 1)`。strace 显示 `ioctl(5, KSU_IOCTL_GRANT_ROOT) = -1 EPERM`。`adb root` 后 UID=0 但 `allowed_for_su()` 返回 false。

**根因**：`kernel/policy/allowlist.c:358-362` 中 `__ksu_is_allow_uid_for_current(0)` 的实现为：
```c
if (unlikely(uid == 0)) {
    return is_ksu_domain();  // 要求进程必须是 u:r:ksu:s0 域
}
```
`adb root` 后进程的 SELinux context 通过 `escape_to_root_for_adb_root()` 设置为 `u:r:su:s0`，而非 `u:r:ksu:s0`。`is_ksu_domain()` 检查 `cached_su_sid` 与当前 SID 是否匹配，由于 context 为 `su` 域而非 `ksu` 域，返回 false → `allowed_for_su()` 返回 false → EPERM。

**修复**：UID 0 时直接 `return true`。UID 0 已经是 root，不存在权限提升风险。`ksud debug su` 从 UID 0 调用 grant_root 应允许。

**教训**：
- `uid == 0` 的快捷路径应直接放行，不应附加 SELinux context 检查
- 不要假设 `adb root` 后进程的 SELinux context 一定是 `ksu` 域
- 根因分析必须读源码，不能仅靠日志推测

**锚点**：`drivers/kernelsu/policy/allowlist.c` — `__ksu_is_allow_uid_for_current()`

**标签**：cross-project

---

## E003：post-fs-data exec 包含 SELinux context 导致 ksud 守护进程无法启动

**现象**：`/system/bin/su` 不存在；`ksud` 系统守护进程不在进程列表；`rootAvailable()` → `Shell.isAppGrantedRoot()` 因 `su -c id` 找不到可执行文件永远返回 false。底部导航栏只有首页和设置两个 Tab（超级用户和模块被 `rootRequired=true` 过滤）。

**根因**：`KERNEL_SU_RC` 中 `on post-fs-data` 的 exec 命令包含 `exec u:r:ksu:s0 root -- ksud post-fs-data`。但 ksu SELinux 域由 `apply_kernelsu_rules()` 在延迟 workqueue（~33s）中创建，而 `post-fs-data` 事件在 ~10-15s 触发。此时 `u:r:ksu:s0` 域不存在，init 无法执行该 exec，ksud 守护进程从未启动。`su` 软链接依赖 `ksud install` 命令安装，ksud 未启动故 `su` 不存在。

**修复**：将 `KERNEL_SU_RC` 中 post-fs-data 的 exec 改为 `exec root -- ksud post-fs-data`（无 SELinux context）。init 进程的 `u:r:init:s0` 域已有 KSU 添加的 `allow init adb_data_file:file *` 规则，有足够权限。

**教训**：
- init.rc 的 `exec` 命令中的 SELinux context 在触发时必须已存在，否则 exec 静默失败
- 延迟创建的 SELinux 域不能用于 early boot 的 init.rc 触发器
- `rootAvailable()` 失败不一定是因为 grant_root 被拒，也可能是 `su` 二进制不存在

**锚点**：`drivers/kernelsu/runtime/ksud_integration.c` — `KERNEL_SU_RC` 字符串中的 post-fs-data exec

**标签**：cross-project

---

## E004：`track_throne()` 在内置路径从未被调用导致管理器 UID 未设置

**现象**：冷启动后 `allowed_for_su()` 中 `is_manager()` 返回 false（`ksu_manager_appid = KSU_INVALID_APPID`）。只有在 `on_boot_completed` 触发后才被设置。管理器 App 启动时管理器 UID 未被识别，`fullFeatured` 为 false。

**根因**：`kernel/core/init.c` 的内置（built-in）路径只调用了 `ksu_throne_tracker_init()`（清空哈希列表），从未调用 `track_throne()` 来扫描 `/data/system/packages.list` 发现管理器 App 的 UID。`track_throne()` 仅在 late-load 路径（`#ifdef MODULE`）中被调用。内置路径中管理器 UID 只有在 `on_boot_completed()` 触发时才通过 `boot_event.c` 的 `track_throne(true)` 设置，此时 App 已经启动完毕并显示了 "grant root failed" 错误。

**修复**：在延迟 workqueue 回调中添加 `track_throne(false)`，并添加最多 5 次重试（每次间隔 2 秒）以应对 `packages.list` 被 Package Manager 锁定的情况。同时添加 `#include "manager/manager_identity.h"` 和 `#include <linux/delay.h>`。

**教训**：
- 内置路径和 LKM 路径的初始化流程不同，`track_throne()` 在 LKM 路径中被调用不意味着在内置路径中也被调用
- 需要验证每个代码路径的执行分支，不能基于一个分支的假设推断另一个
- 系统服务的文件锁（如 `packages.list`）会导致 `track_throne()` 返回而不做任何事，需要重试机制

**锚点**：`drivers/kernelsu/core/init.c` — `ksu_delayed_selinux_init()`（workqueue 回调）

**标签**：cross-project

---

## 当前状态（build #335 验证结果）

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `ksud debug su` 从 adb root | ✅ | `context=u:r:ksu:s0` — Fix 4（uid=0→true）有效 |
| `seccomp_bypass` kprobe 注册 | ❌ | `secure_computing` 符号不存在，返回 -2（ENOENT） |
| `ksud 守护进程` 从 post-fs-data 启动 | ❌ | 查询不到 ksud 系统进程 — Fix 1 未生效或 exec 失败 |
| `track_throne()` 在 workqueue | ❌ | `failed to set manager UID` — 5 次重试全部失败 |
| `system/bin/su` 存在 | ❌ | /system 分区只读，软链接无法创建 |
| 底部导航栏 4 个 Tab | ❌ | `fullFeatured`=false，只显示 Home + Settings |
| 设置页 7 个 feature 开关 | ❌ | 嵌入式 libksud.so 无 KSU fd |

### 未解决问题

1. **`secure_computing` kprobe 失效**：该符号在内核中不可用于 kprobe。需要换为 `__seccomp_filter` 或使用 syscall table hook 方案。
2. **`track_throne()` 失败**：`/data/system/packages.list` 在 workqueue 执行时（33-43s）仍被锁定。需要延长重试窗口到 120s，或使用 `on_boot_completed` 替代。
3. **`su` 不存在**：`/system` 只读分区。需要启用 `KSU_SUSFS_HAS_MAGIC_MOUNT=y` 通过 overlay 挂载 su 软链接。
4. **依赖关系**：上述 3 个问题相互独立，但都导致 App 功能受限。

## 验证检查项

### F01：构建产物验证（刷机前）
- [ ] 构建时间与最新 commit 一致
- [ ] `strings Image | grep uid_zero_fix` — Fix 4 文字常量已嵌入
- [ ] `strings Image | grep NOCTX_FIX` — Fix 1 文字常量已嵌入
- [ ] `strings Image | grep seccomp_bypass` — Fix 2 kprobe 符号已嵌入
- [ ] `nm vmlinux | grep seccomp_bypass_pre` — Fix 2 函数已链接
- [ ] `nm vmlinux | grep ksu_reboot_kprobe_pre` — Fix 2 函数已链接
- [ ] `adb shell zcat /proc/config.gz | grep CONFIG_KSU` — KSU 配置项确认

### F02：启动时序
- [ ] `adb logcat -b events -d -v time | grep boot_progress` — 记录各阶段时间戳
- [ ] `adb logcat -b events -d -v time | grep post_fs_data` — post-fs-data 时间
- [ ] `adb shell dmesg | grep "ksu_debug: delayed init"` — workqueue 执行时间（~33s）
- [ ] `adb shell dmesg | grep "manager UID set"` — track_throne 成功时间
- [ ] `adb logcat -b events -d -v time | grep proc_start | grep rifxsd` — App 启动时间

### F03：Fix 验证
- [ ] F1: `adb shell ps -ef | grep /data/adb/ksu/bin/ksud | grep -v grep` — ksud 守护进程运行中
- [ ] F1: `adb shell ls -la /system/bin/su` — su 软链接存在
- [ ] F2: `adb shell dmesg | grep "seccomp_bypass kprobe registered"` — seccomp_bypass kprobe 注册
- [ ] F2: `adb shell dmesg | grep "ksu_reboot kprobe registered"` — ksu_reboot kprobe 注册
- [ ] F2: `adb logcat -d -v time | grep SYS_SECCOMP | tail -5` — 无新增 SECCOMP crash
- [ ] F2: 设置页 UI dump 确认 7 个 feature 开关全部显示
- [ ] F3: `adb shell cat /sys/module/kernelsu/parameters/ksu_debug_manager_appid` — 管理器 UID 已设置
- [ ] F4: `adb shell dmesg | grep diag:.*allowed_for_su.*is_allow=1` — allowed_for_su 返回 true
- [ ] F4: `adb shell 'echo id | /data/adb/ksu/bin/ksud debug su'` — context=u:r:ksu:s0

### F04：App 功能验证
- [ ] 底部导航栏显示 4 个 Tab（首页、超级用户、模块、设置）
- [ ] 首页无 "授予 root 权限失败" WarningCard
- [ ] 设置页 KernelFeaturesCard 显示全部 7 个开关项
- [ ] 模块页可列出 bindhosts
- [ ] `ksud module list` 正常返回 JSON

### F05：SELinux 审计
- [ ] `adb shell cat /sys/fs/selinux/avc/cache_stats | head -5` — 无新增 avc denial
- [ ] `adb shell cat /data/misc/audit/audit.log 2>/dev/null | grep denied | grep -v libksud | tail -10` — 无 KSU 相关 denial

### F06：稳定性
- [ ] 连续 3 次冷启动每次验证通过
- [ ] 连续 3 次热启动（kill→open）每次验证通过
- [ ] 待机唤醒后验证通过
