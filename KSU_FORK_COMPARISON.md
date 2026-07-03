# KernelSU-Next dev vs legacy 功能差异及移植分析

> 最后更新: 2026-07-03 | 基于源码全量对比
> dev: `8c363a1` (refs/heads/dev)
> legacy: `77b3027` (refs/heads/legacy)

---

## 一、完整差异总表

| 功能 | dev | legacy | 差异 | 移植 | 难度 | 风险 | 重要性 |
|------|:---:|:------:|:----:|:----:|:----:|:----:|:------:|
| **selinux_hide** | `feature/selinux_hide.c` | 内联在 `selinux.c` | 🔴 新架构 | 可移植 | 🔴 高 | 🔴 高 | 🔥 关键 |
| **patch_memory** | `hook/patch_memory.h` + `arm64/patch_memory.c` | ❌ 无 | 🔴 全新 | 可移植 | 🟡 中 | 🔴 高 | 🔥 关键 |
| **symbol_resolver** | `infra/symbol_resolver.c/h` | ❌ 无 | 🔴 全新 | 可移植 | 🟢 低 | 🟢 低 | 🔥 关键 |
| **lsm_hook** | `hook/lsm_hook.c/h` | `hook/lsm_hooks.c` | 🔴 完全重写 | 需适配 | 🔴 高 | 🔴 高 | 🔥 关键 |
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
| `infra/symbol_resolver.c/h` | 简单封装 `kallsyms_lookup_name`，无 4.19 兼容问题 | 🟢 2h | 无 |
| `hook/patch_memory.h` + `arm64/patch_memory.c` | ARM64 文本补丁，使用 `aarch64_insn_patch_text_nosync` + fixmap，4.19 均支持 | 🟡 4h | symbol_resolver |
| `feature/selinux_hide.c/h` | 核心功能，4.19 走 `fake_state` 分支（已有 `#if < 6.6` 路由），不依赖 6.6+ 的内联函数 | 🔴 8h | patch_memory + symbol_resolver + lsm_hook |
| `hook/lsm_hook.c/h` | 基于 `security_hook_heads` 的 LSM 钩子替换，4.19 使用 `struct security_hook_heads`（已有 `#if < 6.12` 分支） | 🔴 8h | symbol_resolver + patch_memory（最终还需要 kallsyms 查找 security_hook_heads 地址） |
| `infra/event_queue.c/h` | 通用事件队列，仅使用基本内核原语（spinlock + waitqueue + list） | 🟢 2h | 无 |
| `sulog/event.c/h` + `feature/sulog.c` + `sulog/fd.c/h` | 完整 sulog 事件子系统，依赖 event_queue | 🟡 6h | event_queue |
| `feature/adb_root.c/h` | ADB Root 功能，通过 `LD_PRELOAD` + `escape_to_root_for_adb_root` | 🟡 4h | 无 |
| `sepolicy` 的 `remove_avtab_node` | 动态规则清理，独立的 30 行函数 | 🟢 1h | 无 |
| `backup_sepolicy` | 策略备份（与 selinux_hide 强关联） | 🟡 3h | sepolicy |
| `allowlist` 哈希化 | 数据结构优化，无内核 API 依赖 | 🟡 2h | 无 |

### ③ 有限可移植（需要大幅适配）

| 功能 | 说明 | 工作量 | 风险 |
|------|------|--------|------|
| `syscall_hook` 系列 | 改用 `sys_call_table` 直接截获、移除 kprobe 机制。legacy 4.19 上 `sys_call_table` 可写，但需要适配符号查找 | 🔴 12h+ | **高** - 修改 sys_call_table 可能被内核锁定保护 |
| `rules.c` 策略新架构 | `dup_sepolicy` + `rcu_assign_pointer` 原子切换。legacy 使用 `stop_machine` + `policy_rwlock`，两者架构不同 | 🔴 16h+ | **高** - SELinux 策略切换若出错会导致系统无安全策略 |
| `supercall/dispatch.c` `do_get_info_legacy` | UAPI v2 兼容层——我们已经通过 `fix-ksu-uapi-v2.py` 实现了自己的版本 | 🟡 4h | **中** - 与现有 fix 脚本冲突风险 |
| `init.c` 初始化顺序 | 需要了解所有模块初始化依赖关系后调整 | 🟡 4h | **中** - 错误顺序导致模块依赖未就绪 |

### ④ 不可移植（架构差异过大或不支持 4.19）

| 功能 | 原因 |
|------|------|
| `lsm_hook.c` 的 dev 完整版 | 依赖 `patch_memory` 和基于内核 6.6+ 的静态调用设施。legacy 4.19 只能用 kprobes 或 `security_hook_heads` 局部替换 |
| `syscall_hook` 的 ARM64 完整版 | 依赖 `sys_call_table` 可写性和新版内核的符号导出，4.19 上可能不同 |
| `throne_tracker` 重写版中的 `apk_path_hash_list` | 性能优化，非功能缺失。legacy 版本功能等价 |
| `x86_64/` 下的所有文件 | 设备为 ARM64，x86_64 代码无关 |

---

## 三、selinux_hide 移植依赖链

```
selinux_hide.c/h
  ├── patch_memory.h + arm64/patch_memory.c  ← 可移植 (4.19 兼容)
  │   └── symbol_resolver.h/c                ← 可移植 (无兼容问题)
  └── lsm_hook.h/c                            ← 需适配 (legacy 有 lsm_hooks.c 但架构不同)
       └── symbol_resolver.h/c                ← 同上
```

### 移植策略建议

**方案 A：全量移植（安全但工作量大）**
1. `symbol_resolver` → 2h
2. `patch_memory` (arm64) → 4h
3. `lsm_hook` (适配 keccy 的 `security_hook_heads` 版本) → 8h
4. `selinux_hide` → 8h
5. `backup_sepolicy` 更新 + `rules.c` 适配 → 4h
6. `init.c` 初始化顺序更新 → 4h
7. 测试 + 编译迭代 → 不定
**总计：~30h + 编译迭代**

**方案 B：最小移植（仅 selinux_hide 核心，用 legacy 已有基础设施）**
1. 不移植 `patch_memory` — 改用 `sel_write_context` 等函数指针直接赋值（内存中的结构体指针可写，不需要 `stop_machine`）
2. 不移植 `lsm_hook` — 用 kprobes 劫持 `selinux_setprocattr`
3. 仅实现 `symbol_resolver`（`kallsyms_lookup_name` 即可）
4. `fake_state` 方式实现 selinux_hide 的 context_write/access_write（4.19 已有 `#if < 6.6` 分支）
**总计：~8h + 编译迭代**

> 方案 B 的可行性已经在 `SELINUX_HIDE_PORT_TO_LEGACY.md` 中作为"方法 B"记录，已在之前的 4 次尝试中被验证过

---

## 四、当前应该优先移植什么

| 优先级 | 功能 | 理由 |
|--------|------|------|
| 🔥 **P0** | `symbol_resolver` | 所有其他移植的基础依赖，简单无风险 |
| 🔥 **P0** | `patch_memory` (arm64) | selinux_hide 的核心依赖，4.19 兼容已验证 |
| 🔥 **P0** | `selinux_hide` | 用户要求的核心功能 |
| 🟡 **P1** | `lsm_hook` (适配版) | 完整功能需要，但可用 kprobes 替代 |
| 🟢 **P2** | `event_queue` + `sulog` 新架构 | 提升用户体验（pollable fd），非安全功能 |
| 🟢 **P2** | `adb_root` | 独立功能，不影响核心 |
| ⏭️ **跳过** | `syscall_hook` 系列 | 架构差异大，legacy 的 kprobe 方式可用 |
| ⏭️ **跳过** | `rules.c` 策略新架构 | 功能等价，只是实现不同 |
| ⏭️ **跳过** | `allowlist` 哈希化 | 纯性能优化 |
