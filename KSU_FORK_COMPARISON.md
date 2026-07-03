# KernelSU-Next dev vs legacy 功能差异及移植分析

> 最后更新: 2026-07-03 | 基于源码全量对比 + GLM 5.2 MAX 报告交叉验证 + 实机验证
> dev: `8c363a1` (refs/heads/dev)
> legacy: `77b3027` (refs/heads/legacy)

---

## 一、完整差异总表

| 功能 | dev | legacy | 差异 | 移植 | 难度 | 风险 | 重要性 |
|------|:---:|:------:|:----:|:----:|:----:|:----:|:------:|
| **selinux_hide (Route A)** | `feature/selinux_hide.c` | 内联在 `selinux.c` | 🔴 新架构 | ✅ **已完成** | 🟢 低 | 🟢 低 | 🔥 关键 |
| **selinux_hide (Route B)** | context/access + backup | ❌ | 🔴 新架构 | ❌ **4.19 不可行** | 🔴 高 | 🔴 高 | 🟡 中 |
| **patch_memory** | `hook/patch_memory.h` + `arm64/patch_memory.c` | ❌ 无 | 🔴 全新 | ⬜ 4.19 不需要（直接赋值替代） | 🟢 低 | 🟢 低 | 🟢 低 |
| **symbol_resolver** | `infra/symbol_resolver.c/h` | ❌ 无 | 🔴 全新 | ✅ **已移植** | 🟢 低 | 🟢 低 | 🟡 中 |
| **lsm_hook** | `hook/lsm_hook.c/h` | `hook/lsm_hooks.c` | 🔴 完全重写 | ⬜ 4.19 用 hlist 遍历替代 | 🟢 低 | 🟢 低 | 🟢 低 |
| **sulog** | `sulog/event.c/fd.c` + `feature/sulog.c` | `tiny_sulog.c` | 🟡 新架构 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **adb_root** | `feature/adb_root.c/h` | ❌ 无 | 🟡 全新 | 可移植 | 🟡 中 | 🟡 中 | 🟡 中 |
| **syscall_hook** | `hook/syscall_hook*`, `syscall_hook_manager` | `hook/hook_manager.c` | 🔴 完全重写 | ⚠️ 有限 | 🔴 高 | 🔴 高 | 🟡 中 |
| **event_queue** | `infra/event_queue.c/h` | ❌ 无 | 🟡 全新 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **allowlist 哈希化** | `HASHTABLE`+`kref` | `LIST_HEAD` | 🟡 重构 | 可移植 | 🟡 中 | 🟡 中 | 🟢 低 |
| **sepolicy 动态清理** | `remove_avtab_node` | ❌ 无 | 🟢 新增 | 可移植 | 🟢 低 | 🟢 低 | 🟢 低 |
| **sepolicy backup** | `backup_sepolicy` | ❌ 无 | 🟢 新增 | ❌ **4.19 不可行** | 🔴 高 | 🔴 高 | 🔥 关键 |
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

### ② 已完成移植

| 功能 | 说明 | 工作量 | 提交 |
|------|------|--------|------|
| **symbol_resolver（简化版）** | 仅 `kallsyms_lookup_name` 封装，无 KCFI/on_each_symbol 等复杂路径 | 🟢 2h | `241ae4b` |
| **selinux_hide Route A** | `my_setprocattr()` — hlist 遍历 `security_hook_heads` 替换 setprocattr hook。auto-enable 通过 `late_initcall` 启动。ksud 编译支持 ID=5 toggle | 🔴 20h+（含 6 次修 bug） | 多轮提交，最终 `f9a77b5` |
| **ksud 编译（ID=5 支持）** | 修改 `feature.rs` 加入 `SelinuxHideNew = 5`，本地交叉编译，推送到设备替换系统 ksud | 🟡 4h | `2be9479` + 本地编译 |

### ③ 可移植（legacy 没有，可以从 dev 移植，4.19 兼容）

| 功能 | 说明 | 工作量 | 前置依赖 | 优先级 |
|------|------|--------|---------|:------:|
| `infra/event_queue.c/h` | 通用事件队列，仅使用基本内核原语（spinlock + waitqueue + list） | 🟢 2h | 无 | 🟡 P1 |
| `sulog/event.c/h` + `feature/sulog.c` + `sulog/fd.c/h` | 完整 sulog 事件子系统，依赖 event_queue | 🟡 6h | event_queue | 🟡 P1 |
| `feature/adb_root.c/h` | ADB Root 功能，通过 `LD_PRELOAD` + `escape_to_root_for_adb_root` | 🟡 4h | 无 | 🟡 P1 |
| **seccomp reset** | root 逃逸时重置 filter_count | 🟢 1h | sucompat | 🟡 P1 |
| **selinux RCU 修复** | get_policydb() 优化 + 非法 RCU 锁修复 | 🟡 2h | selinux/rules | 🟡 P1 |
| **umount 隔离修复** | 修复 zygote 派生进程的 umount 逻辑 | 🟢 1h | kernel_umount | 🟡 P1 |
| **throne OOB 修复** | 越界读修复 + GFP_ATOMIC 替换 | 🟢 1h | throne_tracker | 🟡 P1 |
| **ksu_cred allowlist** | 改用 ksu_cred 保存 allowlist | 🟢 1h | allowlist | 🟢 P2 |
| **stackprotector** | 提供自有 stackprotector 符号 | 🟢 1h | Kbuild | 🟢 P2 |
| **process marking** | 修复 built-in 模式进程标记 | 🟢 1h | init | 🟢 P2 |
| `sepolicy` 的 `remove_avtab_node` | 动态规则清理，独立的 30 行函数 | 🟢 1h | 无 | 🟢 P2 |
| `allowlist` 哈希化 | 数据结构优化，无内核 API 依赖 | 🟡 2h | 无 | 🟢 P2 |

### ④ 有限可移植（需要大幅适配）

| 功能 | 说明 | 工作量 | 风险 |
|------|------|--------|------|
| `syscall_hook` 系列 | 改用 `sys_call_table` 直接截获、移除 kprobe 机制。legacy 4.19 上 `sys_call_table` 可写，但需要适配符号查找 | 🔴 12h+ | **高** - 修改 sys_call_table 可能被内核锁定保护 |
| `rules.c` 策略新架构 | `dup_sepolicy` + `rcu_assign_pointer` 原子切换。legacy 使用 `stop_machine` + `policy_rwlock`，两者架构不同 | 🔴 16h+ | **高** - SELinux 策略切换若出错会导致系统无安全策略 |
| `supercall/dispatch.c` `do_get_info_legacy` | UAPI v2 兼容层——已通过 `fix-ksu-uapi-v2.py` 实现 | 🟡 4h | **中** - 与现有 fix 脚本冲突风险 |
| `init.c` 初始化顺序 | 需要了解所有模块初始化依赖关系后调整 | 🟡 4h | **中** - 错误顺序导致模块依赖未就绪 |
| **GetInfoCmd 修复** | 统一 kernel/ksud/ksuinit 的结构体定义 | 🟡 2h | **中** - 必须与 userspace（ksud/manager）配套，否则通信错位 |
| **KSU_VERSION +150** | 保留 legacy 还是跟随 dev | 🟢 1h | **中** - 需确认 manager 期望的最小内核版本 |

### ⑤ 不可移植或不需要移植（有更简单的 4.19 方案）

| 功能 | 原因 | 4.19 替代方案 |
|------|------|-------------|
| `selinux_hide Route B` (context/access + backup) | `policydb_*` 系列函数在 `security/selinux/ss/policydb.h` 中声明，该头文件仅对 `security/selinux/` 内部可见，KSU 模块无权访问 | **Route A 已足够** — setprocattr 劫持 + 现有 fake status 已完成 |
| `lsm_hook.c` 的 dev 完整版 | 依赖 `patch_memory` 和 6.6+ 静态调用，legacy 无 | **hlist 遍历 `security_hook_heads`** — 4.19 自包含，不需要 lsm_hook |
| `patch_memory` arm64 | dev 用于修改只读代码页 | **不需要** — `write_op[]` 是 kmalloc 内存，直接赋值即可 |
| `syscall_hook` 的 ARM64 完整版 | 依赖 `sys_call_table` 可写性和新版内核符号导出 | legacy 已有 manual hook / kprobes |
| `throne_tracker` 重写版中的 `apk_path_hash_list` | 纯性能优化 | legacy 版本功能等价 |
| `x86_64/` 下的所有文件 | 设备为 ARM64 | 不相关 |

---

## 三、selinux_hide 移植复盘

### 3.1 实际完成情况 vs 原计划

| 原计划 | 实际 | 差异说明 |
|--------|------|----------|
| **Route A**: setprocattr 劫持，4h | ✅ **完成，但实际 20h+** | 6 次编译失败（路径/Wvisibility/static跨文件/policydb.h/死代码消除/initcall 顺序/unhook 崩溃） |
| **Route B**: context/access + backup，4h | ❌ **不可行** | `policydb_*` 是 SELinux SS 内部函数，`security/selinux/ss/policydb.h` 不在 KSU 模块的 include path 中 |
| 注入 `sepolicy.c` | ✅ 完成 | `ksu_backup_policydb()` 非 static 注入，extern void* 声明 |
| 注入 `rules.c` | ✅ 完成 | backup 调用点 |
| 注入 `selinux.h` | ✅ 完成 | void* 声明避免 -Wvisibility |
| `late_initcall` | ✅ 发现并修复 | `ksu_feature_init` 在 device_initcall 清零 feature_handlers |
| 不移除 hook 指针 | ✅ 发现并修复 | `unhook_selinux_setprocattr` 运行时崩溃 |
| ksud ID=5 支持 | ✅ 完成 | 本地编译新 ksud 推送到设备 |

### 3.2 关键教训汇总

| # | 教训 | 对应错误 |
|:-:|------|:--------:|
| 1 | 注入脚本必须检查插入成功，失败返回 False | E002 |
| 2 | 跨模块暴露内部 SELinux 类型必须用 `void *` | E026 |
| 3 | `static` 函数仅在定义它的编译单元内可见 | E027 |
| 4 | `policydb_*` 在 4.19 上不可从 KSU 模块调用 | E028/E029 |
| 5 | feature handler 需 `ksu_register_feature_handler()` 注册，否则死代码消除 | E030 |
| 6 | `ksu_feature_init` 在 device_initcall 清零 feature_handlers，需 late_initcall | E033 |
| 7 | `unhook_selinux_setprocattr` 运行时物理替换 hook 指针导致崩溃 | E034 |
| 8 | Python 三引号中 `\n` 必须写 `\\n` 才能在 C 代码中生成字面量 | E032 |
| 9 | KSU 的 FeatureId 在 userspace 和 kernel 侧各有硬编码列表，必须同步更新 | E031 |

### 3.3 最终架构

```
late_initcall(ksu_selinux_hide_init)
  ├── ksu_register_feature_handler(&selinux_hide_handler)  // ID=5
  ├── hook_selinux_setprocattr()
  │     ├── kallsyms_lookup_name("security_hook_heads")
  │     ├── kallsyms_lookup_name("selinux_setprocattr")
  │     └── hlist_for_each_entry → 替换 hook 指针
  └── ksu_selinux_hide_enabled = true  // auto-enable

ksud feature set 5 0/1 (userspace)
  └── IOCTL → ksu_set_feature(5, value)
        └── selinux_hide_set(value)
              ├── 第一次 enable: hook_selinux_setprocattr() + ksu_selinux_hide_running = true
              └── ksu_selinux_hide_enabled = value  // 仅控制标志位，不物理移除 hook
```

---

## 四、后续移植计划

### 优先级：P1（安全修复 + 常用功能）

| 批次 | 功能 | 工作量 | 风险 | 说明 |
|:----:|------|:------:|:----:|------|
| **Batch 3** | **event_queue + sulog** | 8h | 🟢 低 | event_queue 是 sulog 的基础，sulog 提供完整的事件日志系统替代 tiny_sulog |
| **Batch 3** | **adb_root** | 4h | 🟡 中 | ADB Root 功能，独立，不依赖其他模块 |
| **Batch 3** | **seccomp reset** | 1h | 🟢 低 | 独立 30 行修复，root 逃逸时重置 seccomp |
| **Batch 3** | **umount 隔离修复** | 1h | 🟢 低 | 修复 zygote 派生进程的 umount 逻辑 |
| **Batch 3** | **throne OOB 修复** | 1h | 🟢 低 | 越界读修复 + GFP_ATOMIC 替换 |
| **Batch 3** | **selinux RCU 修复** | 2h | 🟡 中 | get_policydb() 优化 + 非法 RCU 锁用法修复 |

### 优先级：P2（功能优化）

| 批次 | 功能 | 工作量 | 风险 | 说明 |
|:----:|------|:------:|:----:|------|
| **Batch 4** | **ksu_cred allowlist** | 1h | 🟢 低 | 改用 ksu_cred 保存 allowlist |
| **Batch 4** | **stackprotector** | 1h | 🟢 低 | 提供自有 stackprotector 符号 |
| **Batch 4** | **process marking** | 1h | 🟢 低 | 修复 built-in 模式进程标记 |
| **Batch 4** | **allowlist 哈希化** | 2h | 🟢 低 | 数据结构优化，性能提升 |
| **Batch 4** | **sepolicy 动态清理** | 1h | 🟢 低 | `remove_avtab_node`，独立 30 行函数 |

### 优先级：P3（低优先/待评估）

| 功能 | 工作量 | 风险 | 说明 |
|------|:------:|:----:|------|
| **KSU_VERSION +150 决策** | 1h | 🟡 中 | 需确认 manager 期望的版本基线 |
| **GetInfoCmd 修复** | 2h | 🟡 中 | 需与 userspace 配套 |
| **init.c 初始化顺序调整** | 4h | 🟡 中 | 需了解所有模块初始化依赖关系 |
| **supercall 增强** | 4h | 🟡 中 | sulog + legacy 兼容 |

### 跳过（不移植）

| 功能 | 理由 |
|------|------|
| `selinux_hide Route B` | `policydb_*` 不可从 KSU 模块调用，4.19 架构限制 |
| `syscall_hook` 系列 | 架构差异大，legacy 的 kprobe 方式可用 |
| `rules.c` 策略新架构 | 功能等价，只是实现不同 |
| `syscall_event_bridge` / `tp_marker` | 依赖新钩子基础设施 |
| `arm64 内联 syscall hook` | Cortex-A77 (ARMv8.2) 存在已知 su 兼容问题 |

---

## 五、严重警告

| 级别 | 警告 | 说明 |
|:----:|------|------|
| 🔴 **致命** | 不要删除 `compat/kernel_compat.c/.h` | dev 已裁剪 4.x 支持，但你的 OnePlus 8T 是 Linux 4.19，compat 层是它在 4.x 内核上编译/运行的根基。删除会导致大量符号未定义，直接编译失败或开机 panic |
| 🔴 **致命** | 不要删除 legacy Kbuild 的源码回退补丁块 | legacy Kbuild 用 sed 自动给 4.19 内核源码打补丁（can_umount / path_umount / struct seccomp filter_count / selinux_inode / selinux_cred / Samsung KDP 检测等）。dev 已删除该块。保留它，否则编译期找不到这些符号 |
| 🟡 **高** | 谨慎启用 arm64 内联 syscall hook | v1.1.1 hotfix 因「旧 ARMv8.0–8.2 CPU 上的未知 su 兼容问题」将 syscall hook 从 v1.5 回退到 v1.4。OnePlus 8T 大核 Cortex-A77 属 ARMv8.2-A，正好落在受影响区间 |
| 🟡 **高** | kernel 侧结构体改动必须与 ksud/manager 同步 | GetInfoCmd、app_profile 结构等一旦在 kernel 侧改动，userspace 必须使用匹配版本，否则通信错位导致 root 失效或崩溃 |
| 🟡 **中** | KSU_VERSION 偏移需确认 | legacy 的 `+150` 偏移与 manager 期望的版本判定可能有关，改动前确认你的 userspace 基线 |
| 🟡 **中** | 始终保留原始 boot.img 与可回退路径 | 每次出包前确认回退流程：保留 stock boot.img，失败时 `fastboot flash boot_a 原始镜像` |
| 🟡 **中** | 移植 p1 功能前先备份当前正常工作的 ksud 和 boot.img | 每次修改可能导致编译失败或刷机崩溃 |

---

## 六、下次移植目标（推荐 Batch 3）

### 推荐顺序

| 步骤 | 功能 | 预计时间 | 原因 |
|:----:|------|:--------:|------|
| 1 | **event_queue** | 2h | 基础依赖，sulog 需要它 |
| 2 | **sulog** | 6h | 完整事件日志系统，替代 tiny_sulog |
| 3 | **adb_root** | 4h | 常用功能，独立移植 |
| 4 | **seccomp reset** | 1h | 安全修复，独立 30 行 |
| 5 | **umount 隔离修复** | 1h | 稳定性修复 |
| 6 | **throne OOB 修复** | 1h | 安全修复 |
| 7 | **selinux RCU 修复** | 2h | 稳定性修复 |

### 移植原则

1. **一次只移植一个函数** — 每个功能独立提交，独立测试
2. **所有 bug 必须有根因分析才提交** — 记录到 ERRORS.md
3. **提交前 pre-flight-check 0 阻断**
4. **每次刷机前备份当前系统 boot 分区**