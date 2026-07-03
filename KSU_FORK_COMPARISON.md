# KernelSU-Next dev vs legacy 功能差异及移植分析

> 最后更新: 2026-07-03 | 基于源码全量对比 + GLM 5.2 MAX 报告交叉验证
> dev: `8c363a1` (refs/heads/dev)
> legacy: `77b3027` (refs/heads/legacy)

---

## 一、完整差异总表

| 功能 | dev | legacy | 差异 | 移植 | 难度 | 风险 | 重要性 |
|------|:---:|:------:|:----:|:----:|:----:|:----:|:------:|
| **selinux_hide** | `feature/selinux_hide.c` | 内联在 `selinux.c` | 🔴 新架构 | 可移植 | 🟢 低 | 🟢 低 | 🔥 关键 |
| **patch_memory** | `hook/patch_memory.h` + `arm64/patch_memory.c` | ❌ 无 | 🔴 全新 | ⬜ 4.19 不需要（直接赋值替代） | 🟢 低 | 🟢 低 | 🟢 低 |
| **symbol_resolver** | `infra/symbol_resolver.c/h` | ❌ 无 | 🔴 全新 | 可移植 | 🟢 低 | 🟢 低 | 🟡 中 |
| **lsm_hook** | `hook/lsm_hook.c/h` | `hook/lsm_hooks.c` | 🔴 完全重写 | ⬜ 4.19 用 hlist 遍历替代 | 🟢 低 | 🟢 低 | 🟢 低 |
| **sulog** | `sulog/event.c/fd.c` + `feature/sulog.c` | `tiny_sulog.c` | 🟡 新架构 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **adb_root** | `feature/adb_root.c/h` | ❌ 无 | 🟡 全新 | 可移植 | 🟡 中 | 🟡 中 | 🟡 中 |
| **syscall_hook** | `hook/syscall_hook*`, `syscall_hook_manager` | `hook/hook_manager.c` | 🔴 完全重写 | ⚠️ 有限 | 🔴 高 | 🔴 高 | 🟡 中 |
| **event_queue** | `infra/event_queue.c/h` | ❌ 无 | 🟡 全新 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **allowlist 哈希化** | `HASHTABLE`+`kref` | `LIST_HEAD` | 🟡 重构 | 可移植 | 🟡 中 | 🟡 中 | 🟢 低 |
| **sepolicy 动态清理** | `remove_avtab_node` | ❌ 无 | 🟢 新增 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **sepolicy backup** | `backup_sepolicy` | ❌ 无 | 🟢 新增 | 需配合 selinux_hide | 🟡 中 | 🟡 中 | 🔥 关键 |
| **rules.c 策略新架构** | `dup_sepolicy`+`rcu_assign` | `stop_machine`+`rwlock` | 🔴 重写 | ⚠️ 需评估 | 🔴 高 | 🔴 高 | 🔥 关键 |
| **sucompat 清理** | 无 compat 依赖 | 有 compat 依赖 | 🟢 清理 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **setuid_hook 简化** | 同步 `ksu_install_fd` | `task_work` 延迟 | 🟡 简化 | 可移植 | 🟢 低 | 🟡 中 | 🟡 中 |
| **compat/kernel_compat** | ❌ 已移除 | ✅ 有 | 🟢 legacy 有 | **无需移植** | — | — | — |
| **tiny_sulog** | ❌ 已移除 | ✅ 有 | 🟢 legacy 有 | **无需移植** | — | — | — |
| **pkg_observer_defs** | ❌ 内联 | ✅ 独立文件 | 🟢 legacy 有 | **无需移植** | — | — | — |
| **init.c 初始化流程** | 重构初始化顺序 | 旧顺序 | 🔴 重排 | 需适配 | 🟡 中 | 🟡 中 | 🔥 关键 |
| **supercall/dispatch** | sulog + legacy 兼容 | 无兼容 | 🟡 增强 | 需适配 | 🟡 中 | 🟡 中 | 🔥 关键 |
| **throne_tracker 重写** | 哈希加速+分段 | 线性扫描 | 🟡 重构 | 可移植 | 🟡 中 | 🟡 中 | 🟢 低 |
| **pkg_observer** | 移除旧版兼容 | 有兼容 | 🟢 清理 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **arch.h** | 新 syscall 符号 | 旧符号 | 🟡 更新 | 需适配 | 🟢 低 | 🟢 低 | 🟡 中 |
| **ksu.h** | 新声明 | 旧声明 | 🟡 更新 | 需适配 | 🟢 低 | 🟢 低 | 🟡 中 |

### 零散修复清单（GLM 逐项识别，补充到总表）

| 功能 | dev | legacy | 差异 | 移植 | 风险 | 说明 |
|------|:---:|:------:|:----:|:----:|:----:|------|
| **seccomp reset** | ✅ | ❌ | 🟢 新增 | 可移植 | 🟢 低 | root 逃逸时重置 seccomp filter_count，避免遗留约束影响 root 进程 |
| **selinux RCU 修复** | ✅ | ❌ | 🟢 修复 | 可移植 | 🟡 中 | `get_policydb()` 微优化 + handle_sepolicy() 中非法 RCU 锁用法修复 |
| **umount 隔离修复** | ✅ | ❌ | 🟢 修复 | 可移植 | 🟢 低 | 修复从 zygote 派生的隔离进程未正确卸载模块挂载的问题 |
| **throne_tracker OOB 修复** | ✅ | ❌ | 🟢 修复 | 可移植 | 🟢 低 | 越界读（OOB read）修复 + GFP_ATOMIC 替换为更合适的分配标志 |
| **ksu_cred allowlist** | ✅ | ❌ | 🟢 新增 | 可移植 | 🟢 低 | 改用 `ksu_cred` 保存 allowlist，提升一致性与安全性 |
| **stackprotector** | ✅ | ❌ | 🟢 新增 | 可移植 | 🟢 低 | 提供自有 `__stack_chk_guard`/`__stack_chk_fail`，解决链接期 undefined reference |
| **process marking** | ✅ | ❌ | 🟢 修复 | 可移植 | 🟢 低 | 修复 built-in 模式下进程标记逻辑，确保 root 授权判定正确 |
| **GetInfoCmd 修复** | ✅ | ❌ | 🟢 修复 | ⚠️ 需配套 | 🟡 中 | 统一 kernel/ksud/ksuinit 三处的结构体定义，kernel 侧改动需 userspace 配套 |
| **KSU_VERSION +150** | 去掉+150 | 保留+150 | 🟡 差异 | 待决策 | 🟡 中 | legacy 的 KSU_VERSION = 30000 + git_version + 150；dev 去掉了 +150。需与 manager 版本约定保持一致 |

---

## 二、按移植类别分组

### ① 已等价（legacy 已有，无需移植）

| 功能 | 说明 |
|------|------|
| `compat/kernel_compat.c/h` | legacy 专有的内核 API 兼容层，dev 已移除（直接使用标准 API） |
| `tiny_sulog.c/h` | legacy 的简单 sulog 实现，dev 用完整事件子系统替代 |
| `pkg_observer_defs.h` | legacy 的宏兼容定义，dev 内联到源文件 |
| 基础架构文件（大部分同名文件） | `feature/kernel_umount`, `infra/file_wrapper`, `infra/seccomp_cache`, `runtime/boot_event` 等差异较小，功能等价 |

### ② 可移植（legacy 没有，可以从 dev 移植，4.19 兼容）

| 功能 | 说明 | 工作量 | 前置依赖 |
|------|------|--------|---------|
| **selinux_hide 路线 A** | setprocattr 劫持 + hlist 遍历 `security_hook_heads`，并入 `selinux.c`，不改 Kbuild | 🟢 4h | 无（`kallsyms_lookup_name` 直接找符号） |
| **selinux_hide 路线 B** | 路线 A + write+read 全量备份 + `my_write_context/access` + fake `selinux_ss` | 🟡 4h | 路线 A 先通过 |
| `infra/event_queue.c/h` | 通用事件队列，仅使用基本内核原语（spinlock + waitqueue + list） | 🟢 2h | 无 |
| `sulog/event.c/h` + `feature/sulog.c` + `sulog/fd.c/h` | 完整 sulog 事件子系统，依赖 event_queue | 🟡 6h | event_queue |
| `feature/adb_root.c/h` | ADB Root 功能，通过 `LD_PRELOAD` + `escape_to_root_for_adb_root` | 🟡 4h | 无 |
| `sepolicy` 的 `remove_avtab_node` | 动态规则清理，独立的 30 行函数 | 🟢 1h | 无 |
| `allowlist` 哈希化 | 数据结构优化，无内核 API 依赖 | 🟡 2h | 无 |
| **seccomp reset** | root 逃逸时重置 filter_count | 🟢 1h | sucompat |
| **selinux RCU 修复** | get_policydb() 优化 + 非法 RCU 锁修复 | 🟡 2h | selinux/rules |
| **umount 隔离修复** | 修复 zygote 派生进程的 umount 逻辑 | 🟢 1h | kernel_umount |
| **throne OOB 修复** | 越界读修复 + GFP_ATOMIC 替换 | 🟢 1h | throne_tracker |
| **ksu_cred allowlist** | 改用 ksu_cred 保存 allowlist | 🟢 1h | allowlist |
| **stackprotector** | 提供自有 stackprotector 符号 | 🟢 1h | Kbuild |
| **process marking** | 修复 built-in 模式进程标记 | 🟢 1h | init |

### ③ 有限可移植（需要大幅适配）

| 功能 | 说明 | 工作量 | 风险 |
|------|------|--------|------|
| `syscall_hook` 系列 | 改用 `sys_call_table` 直接截获、移除 kprobe 机制。legacy 4.19 上 `sys_call_table` 可写，但需要适配符号查找 | 🔴 12h+ | **高** - 修改 sys_call_table 可能被内核锁定保护 |
| `rules.c` 策略新架构 | `dup_sepolicy` + `rcu_assign_pointer` 原子切换。legacy 使用 `stop_machine` + `policy_rwlock`，两者架构不同 | 🔴 16h+ | **高** - SELinux 策略切换若出错会导致系统无安全策略 |
| `supercall/dispatch.c` `do_get_info_legacy` | UAPI v2 兼容层——我们已经通过 `fix-ksu-uapi-v2.py` 实现了自己的版本 | 🟡 4h | **中** - 与现有 fix 脚本冲突风险 |
| `init.c` 初始化顺序 | 需要了解所有模块初始化依赖关系后调整 | 🟡 4h | **中** - 错误顺序导致模块依赖未就绪 |
| **GetInfoCmd 修复** | 统一 kernel/ksud/ksuinit 的结构体定义 | 🟡 2h | **中** - 必须与 userspace（ksud/manager）配套，否则通信错位 |
| **KSU_VERSION +150** | 保留 legacy 还是跟随 dev | 🟢 1h | **中** - 需确认 manager 期望的最小内核版本 |

### ④ 不可移植或不需要移植（有更简单的 4.19 方案）

| 功能 | 原因 | 4.19 替代方案 |
|------|------|-------------|
| `lsm_hook.c` 的 dev 完整版 | 依赖 `patch_memory` 和 6.6+ 静态调用，legacy 无 | **hlist 遍历 `security_hook_heads`** — 4.19 自包含，不需要 lsm_hook |
| `patch_memory` arm64 | dev 用于修改只读代码页 | **不需要** — `write_op[]` 是 kmalloc 内存，直接赋值即可 |
| `syscall_hook` 的 ARM64 完整版 | 依赖 `sys_call_table` 可写性和新版内核符号导出 | legacy 已有 manual hook / kprobes |
| `throne_tracker` 重写版中的 `apk_path_hash_list` | 纯性能优化 | legacy 版本功能等价 |
| `x86_64/` 下的所有文件 | 设备为 ARM64 | 不相关 |

---

## 三、selinux_hide 完整移植方案（基于 GLM 5.2 MAX 报告 + 4.19 验证）

### 3.1 GLM 方案 vs 我们原方案 vs Arena 方案

| 维度 | ❌ 我们原方案 A | ❌ Arena 方案 | ✅ GLM 方案（采用） |
|------|:-------------:|:-------------:|:----------------:|
| `patch_memory` | 需要（全量移植） | 需要（新建文件） | **不需要** — `write_op[]` 是 kmalloc 内存，直接赋值即可 |
| `lsm_hook` | 需要 | 未处理 | **不需要** — 用 hlist 遍历 `security_hook_heads` 替换 setprocattr |
| 文件组织 | 新建 `feature/selinux_hide.c` | 新建 `feature/selinux_hide.c` | **并入 `selinux.c` / `sepolicy.c`** — 不改 Kbuild |
| Kbuild 改动 | 需要 | 需要 | **不需要** |
| 4.19 `selinux_ss` | 未分析 | 未处理 | **完整处理** — 用 fake `selinux_ss` 替代 dev 的 `selinux_policy` |
| backup 方案 | 依赖 dev 的 `ksu_dup_sepolicy` | 未处理 | **write+read 全量副本** — 4.19 可用的 `ksu_backup_policydb()` |
| 符号查找 | 依赖 `symbol_resolver` | `kallsyms_lookup_name` | **`kallsyms_lookup_name`** 直接够用 |
| setprocattr 劫持 | kprobes | 未处理 | **hlist 遍历 `security_hook_heads`** — 4.19 自包含 |
| init.c 改动 | 需要改初始化顺序 | 需要 | **几乎不用改**（代码并入 selinux.c，backup 在 rules.c 中触发） |
| **总体风险** | 🔴 高 | 🔴 高 | 🟢 **低** |
| **工作量** | ~30h | ~16h | **~8h（路线A 4h + 路线B 4h）** |

### 3.2 方案概述

GLM 方案的核心思路：**不建新文件，不引入 patch_memory/lsm_hook 依赖，充分复用 legacy 已有的基础设施。**

所有代码写入两个已编译文件：
- `selinux/selinux.c` — `write_op[]` 劫持 + `setprocattr` 劫持 + feature 开关 + fake backup 容器
- `selinux/sepolicy.c` — 全量备份函数 `ksu_backup_policydb()`
- `selinux/rules.c` — 在 `apply_kernelsu_rules()` 改写策略前插入快照调用

**Kbuild 无需任何改动。** 因为不新建编译单元。

### 3.3 依赖链（简化后）

```
selinux_hide (并入 selinux.c)
  ├── kallsyms_lookup_name("write_op")           ← 直接调用，无需 symbol_resolver 封装
  ├── kallsyms_lookup_name("security_hook_heads")← 同上
  ├── kallsyms_lookup_name("selinux_setprocattr")← 同上
  └── backup_sepolicy:
       ├── policydb_write(src, &fp)              ← selinux 原生函数，4.19 有
       └── policydb_read(dst, &fp)               ← selinux 原生函数，4.19 有
```

**patch_memory / lsm_hook / symbol_resolver 全部不需要。**

### 3.4 移植策略

**路线 A（先做，低风险）：setprocattr 劫持 + 现有 fake status**
- 已有：fake status page（`sel_handle_status_ops` 已由 legacy 内联实现）
- 新增：`my_setprocattr()` — 通过 hlist 遍历替换 `security_hook_heads.setprocattr`
- 不需要 backup（setprocattr 用真实策略降级而非替代）
- **预计 1 次编译通过**
- 收益：隐藏 enforcing/permissive 状态 + app 改自己上下文的探测

**路线 B（路线 A 通过后叠加）：context/access 劫持**
- 新增：`ksu_backup_policydb()` 全量快照
- 新增：fake `selinux_ss` 容器 + `ksu_fake_state`
- 新增：`my_write_context()` / `my_write_access()` 用 fake_state 回答
- 收益：app 用 `selinux_check_context` / `selinux_check_access` 也看不到 ksu 域
- 预估：路线 A 基础上再 +4h

### 3.5 4.19 关键适配点

| 点 | dev（6.x） | 4.19 | 对策 |
|---|-----------|------|------|
| 策略容器 | `struct selinux_policy *` | `struct selinux_ss *` | 用 fake `selinux_ss`，`ksu_fake_state.ss = &ksu_backup_ss` |
| backup | `ksu_dup_sepolicy()`（5.10+） | 不存在 | 自实现 `ksu_backup_policydb()`：policydb_write → policydb_read |
| LSM 链表 | `list_head` | `hlist_head` + `hlist_node` | 用 `hlist_for_each_entry` 遍历 |
| 文本补丁 | `ksu_patch_text()` | 不需要 | 直接赋值 `write_op[]` 元素（kmalloc 内存，可写） |
| 大内核锁 | 已去掉 | 存在 `policy_rwlock` | 备份时 `read_lock` 后操作 |

### 3.6 之前 4 次失败的根本原因

| 提交 | 失败点 | GLM 方案如何避免 |
|------|--------|-----------------|
| 47a1a4e | Kbuild 锚点错 | **不建新文件，Kbuild 不动** |
| aa4f796 | 链接期缺 `patch_memory.h` | **直接赋值，整条 patch_memory 依赖砍掉** |
| 55b86fa | 仍缺 `ksu_patch_text()` | **同上——根本不需要文本补丁** |
| 62d0d0a | Revert | — |

---

## 四、当前应该优先移植什么

| 优先级 | 功能 | 理由 |
|--------|------|------|
| 🔥 **P0** | `selinux_hide` 路线 A（setprocattr） | 先用 `kallsyms_lookup_name` 直接查找符号，hlist 遍历劫持 setprocattr。不需要 `symbol_resolver`/`patch_memory`/`lsm_hook` |
| 🔥 **P0** | `selinux_hide` 路线 B（context/access + backup） | 路线 A 通过后叠加。需 `ksu_backup_policydb()` + fake `selinux_ss` 容器 |
| 🟡 **P1** | 零散修复（seccomp reset / selinux RCU / umount / throne OOB 等） | 独立逻辑，风险低 |
| 🟡 **P1** | `symbol_resolver` | **已移植**（简化版，仅 `kallsyms_lookup_name` 封装）。实际上 selinux_hide 不需要它，但其他功能可能用 |
| 🟢 **P2** | `event_queue` + `sulog` 新架构 | 提升用户体验，非安全功能 |
| 🟡 **P1** | `selinux RCU 修复` | 降低死锁/崩溃风险 |
| 🟡 **P1** | `umount 隔离修复` | 提升隐藏稳定性 |
| 🟡 **P1** | `throne OOB 修复` | 安全修复（越界读） |
| 🟡 **P1** | `ksu_cred allowlist` | 一致性改进 |
| 🟡 **P1** | `stackprotector` | 解决编译期潜在问题 |
| 🟡 **P1** | `process marking` | 修复 built-in 模式 root 判定 |
| 🟡 **P1** | `lsm_hook` (适配版) | 完整功能需要，但可用 kprobes 替代 |
| 🟢 **P2** | `event_queue` + `sulog` 新架构 | 提升用户体验（pollable fd），非安全功能 |
| 🟢 **P2** | `adb_root` | 独立功能，不影响核心 |
| 🟢 **P2** | `allowlist` 哈希化 | 纯性能优化 |
| 🟢 **P2** | `KSU_VERSION` 决策 | 需与 manager 版本约定保持一致 |
| ⏭️ **跳过** | `syscall_hook` 系列 | 架构差异大，legacy 的 kprobe 方式可用 |
| ⏭️ **跳过** | `rules.c` 策略新架构 | 功能等价，只是实现不同 |
| ⏭️ **跳过** | `syscall_event_bridge` / `tp_marker` | 依赖新钩子基础设施 |
| ⏭️ **跳过** | `arm64 内联 syscall hook` | Cortex-A77 (ARMv8.2) 存在已知 su 兼容问题，v1.1.1 hotfix 已回退 |

---

## 五、严重警告（借鉴 GLM 报告）

| 级别 | 警告 | 说明 |
|:----:|------|------|
| 🔴 **致命** | 不要删除 `compat/kernel_compat.c/.h` | dev 已裁剪 4.x 支持，但你的 OnePlus 8T 是 Linux 4.19，compat 层是它在 4.x 内核上编译/运行的根基。删除会导致大量符号未定义，直接编译失败或开机 panic |
| 🔴 **致命** | 不要删除 legacy Kbuild 的源码回退补丁块 | legacy Kbuild 用 sed 自动给 4.19 内核源码打补丁（can_umount / path_umount / struct seccomp filter_count / selinux_inode / selinux_cred / Samsung KDP 检测等）。dev 已删除该块。保留它，否则编译期找不到这些符号 |
| 🟡 **高** | 谨慎启用 arm64 内联 syscall hook | v1.1.1 hotfix 因「旧 ARMv8.0–8.2 CPU 上的未知 su 兼容问题」将 syscall hook 从 v1.5 回退到 v1.4。OnePlus 8T 大核 Cortex-A77 属 ARMv8.2-A，正好落在受影响区间 |
| 🟡 **高** | kernel 侧结构体改动必须与 ksud/manager 同步 | GetInfoCmd、app_profile 结构等一旦在 kernel 侧改动，userspace 必须使用匹配版本，否则通信错位导致 root 失效或崩溃 |
| 🟡 **中** | KSU_VERSION 偏移需确认 | legacy 的 `+150` 偏移与 manager 期望的版本判定可能有关，改动前确认你的 userspace 基线 |
| 🟡 **中** | 始终保留原始 boot.img 与可回退路径 | 每次出包前确认回退流程：保留 stock boot.img，失败时 `fastboot flash boot_a 原始镜像` |

---

## 六、移植工作流（参考 GLM 分阶段建议）

| 阶段 | 内容 | 风险 |
|:----:|------|:----:|
| **1. 准备** | 在 KernelSU-Next 上基于 legacy 新建工作分支，同时检出 dev 作为参照源 | 🟢 |
| **2. 安全同步** | 逐个 sync 低风险文件（`feature/kernel_umount`、`infra/*`、`manager/*`、`policy/*`、`runtime/*`、`supercall/*`）；新增 `event_queue`、`symbol_resolver`、`adb_root`、`sulog`；保留 `compat/` 与 Kbuild 回退补丁块 | 🟢 |
| **3. 谨慎合并** | `core/init.c`、`feature/sucompat.c`、`selinux/*` 三路合并，保留 4.19 条件宏；改名文件同步更新 Kbuild 与 `#include`；替换 `tiny_sulog` → `sulog` | 🟡 |
| **4. 高风险评估** | arm64 内联 syscall hook 默认不启用；`syscall_event_bridge` / `tp_marker` 视新钩子基础设施落地情况决定 | 🔴 |
| **5. 同步到内核树** | 移植后的 KSU 放入 4.19 内核树 `drivers/kernelsu/`；`ksu.config` 中确保 `CONFIG_KSU=y`，hook 模式推荐 manual hook | 🟡 |
| **6. CI 编译验证** | 推送触发 GHA，关注 KernelSU 注入段输出（version、hook mode、各补丁注入信息） | 🟡 |
| **7. 实机验证** | `fastboot boot` 临时启动，验证 root 授权、SUSFS 隐藏、各功能正常 | 🔴 |

