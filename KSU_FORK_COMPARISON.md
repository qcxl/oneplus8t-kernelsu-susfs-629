# KernelSU-Next dev → legacy 移植进度总表

> 最后更新: 2026-07-04 | 基于源码全量对比 + GLM 5.2 MAX + Arena 交叉验证 + 实机验证
> dev: `8c363a1` | legacy: `77b3027` | 设备: OnePlus 8T (kebab), kernel 4.19.304

---

## 🎯 总体进度

```
移植完成度:     ████████████████████████████████  100% (9/9 可移植功能)
调研完成度:     ████████████████████████████████ 100%  (5/5)
```

| 分类 | 总计 | ✅ 完成 | ⏳ 待集成 | ❌ 不可行 | ⬜ 已有等效 |
|:----|:---:|:------:|:--------:|:--------:|:----------:|
| 可移植功能 | 9项 | **9** | 0 | 0 | 0 |
| 不可移植（4.19 限制） | 8项 | — | — | **8** | — |
| 已有等效（legacy 已有） | 7项 | — | — | — | **7** |
| 🔍 调研 | 5项 | **5**已出结论 | 0 | 0 | 0 |

---

## 一、✅ 已完成移植（9项，全部通过刷机验证）

```
selinux_hide (GLM完整版)    ████████████████████ 100%  context+access+setprocattr
sulog + event_queue         ████████████████████ 100%  替代 tiny_sulog
adb_root                    ████████████████████ 100%  execve 劫持 + LD_PRELOAD
symbol_resolver             ████████████████████ 100%  kallsyms_lookup_name 封装
ksud 交叉编译 (ID=5)        ████████████████████ 100%  支持 toggle
remove_avtab_node           ████████████████████ 100%  冗余 avtab 清理（flex_array 适配）
setuid_hook spin_lock       ████████████████████ 100%  并发安全保护
```

| 功能 | 说明 | 工作量 | 提交/来源 |
|------|------|:------:|-----------|
| **selinux_hide（GLM 完整版）** | 过滤模式（`:ksu:` 字符串检测），context_write + access_write + setprocattr 三个钩子，`write_op[]` 直接赋值，`security_hook_heads` hlist 遍历 | 🔴 25h | `e904f34` |
| **sulog 子系统** | 完整 event_queue + sulog event/fd 实现，替代 `tiny_sulog`。4.19 兼容：`strncpy_from_user_nofault→strncpy_from_user`，`minmax.h→kernel.h` | 🟢 8h | `6dbf6f4` + `c092fdd` + `061ec8d` |
| **adb_root** | execve 劫持注入 LD_PRELOAD。4.19 兼容：`user_stack_pointer→PT_REGS_SP`，`transive_to_domain` 2参数 | 🟡 4h | `73b57c5` + `265648f` + `932facc` |
| **event_queue** | 通用事件队列（spinlock + waitqueue + list），sulog 的基础依赖 | 🟢 2h | `6dbf6f4` |
| **symbol_resolver** | 简化版，仅 `kallsyms_lookup_name` 封装 | 🟢 2h | `241ae4b` |
| **ksud 交叉编译** | 本地编译支持 ID=5 (`SelinuxHideNew = 5`) 的 ksud，推送到设备 | 🟡 4h | `2be9479` + 本地编译 |
| **remove_avtab_node** | 冗余 avtab 节点自动清理。4.19 适配：`flex_array_get/put_ptr` 替代直接数组访问 | 🟢 2h | `fab6acf` + `dc86ccc` |
| **setuid_hook spin_lock** | 添加 spin_lock_irq 保护 seccomp_allow_cache 调用，防止竞争 | 🟢 1h | `fab6acf` |
| **GLM_PROMPT.md** | 后续移植任务的完整 prompt，可直接发给 GLM 5.2 | 🟢 15min | `fab6acf` |

---

## 二、🔴 不可移植/不需要移植（5项）

```
policydb_* 函数访问       ████████████████████ 100%  已确认：4.19 KSU 模块不可访问
syscall_table 写保护      ████████████████████ 100%  已确认：rodata 段只读
selinux_ss vs policy      ████████████████████ 100%  已确认：4.19 架构不兼容
backup_sepolicy           ████████████████████ 100%  过滤模式已等效
Cortex-A77 兼容性         ████████████████████ 100%  A77 非直接障碍，但 sys_call_table 写保护是
```

| 功能 | 不可行原因 | 4.19 替代方案 |
|------|-----------|-------------|
| **selinux_hide Route B（backup）** | ① `policydb_write/read/init/destroy` 声明在 `security/selinux/ss/policydb.h`（387行），该头文件通过 `#include "symtab.h"`/`"avtab.h"` 等链式引用 SELinux SS 内部类型。虽然 `-I$(srctree)/security/selinux` 在 Kbuild 中，包含路径可达，但 `policydb_init()` 是 `static` 函数（`security/selinux/ss/policydb.c:283`），外部模块不能调用。② dev 的 `ksu_dup_sepolicy` 接受 `struct selinux_policy *`（5.10+），4.19 用 `struct selinux_ss *`，两者字段差一个 `policy_rwlock`（4.19 有）和 `rcu_head`（dev 有），不能通用。③ `security_context_to_sid_with_policy` 在 4.19 不存在（dev 的 `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6,6,0)` 块中有 300 行内联实现）。总工作量 25h+。 | 过滤模式（已完成） |
| **patch_memory arm64** | dev 用 `ksu_patch_text()` 修改只读代码页，依赖 `stop_machine` + fixmap（`FIX_TEXT_POKE0`）+ `copy_to_kernel_nofault` 完整栈。`copy_to_kernel_nofault` 是 5.4+ 才有的 API，4.19 只有 `probe_kernel_write`。`set_fixmap_offset` 虽在 4.19 arm64 存在，但 `FIX_TEXT_POKE0` 的枚举值可能与 dev 假设不同。 | `write_op[]` 直接赋值（已验证可行） |
| **lsm_hook 完整版** | dev 的 `ksu_lsm_hook()` 框架在 `hook/lsm_hook.c` 中，依赖 `patch_memory` 修改 security_hook_heads 链表（通过文本补丁替换 LSM hook 函数指针）。4.19 没有 `patch_memory`，且 `security_hook_heads` 链表在 4.19 中用 `hlist_head`+`hlist_node`（非 dev 的 `list_head`）。 | hlist 遍历 `security_hook_heads`（已验证可行） |
| **syscall_hook arm64 完整版** | ① `sys_call_table` 在 4.19 arm64 `.rodata` 段，`CONFIG_RODATA_FULL_DEFAULT_ENABLED=y` 下只读，需要 `set_memory_rw()` 临时解除写保护——这是 hack 方式，稳定性存疑。② 需要 `CONFIG_KALLSYMS_ALL=y` 才能从 kallsyms 查到 `sys_call_table` 地址（data 段符号），用户项目的 `ksu.config` 是否开启不确定。③ 需要 `copy_to_kernel_nofault`（4.19 用 `probe_kernel_write` 替代）。④ Cortex-A77 有历史回退记录（v1.1.1 hotfix）。⑤ 总工作量 30h+，包括新建 7+ 文件、删除 `hook_manager.c`、重写 `sucompat.c`、修改 `setuid_hook.c`/`ksud_integration.c` 等。 | legacy kprobe 方式可用 |
| **rules.c 策略新架构** | 4.19 `struct selinux_ss` 的 `struct policydb policydb` 是**内嵌字段**（不是指针），`struct sidtab *sidtab` 是唯一可以替换的指针。dev 用 `rcu_assign_pointer(selinux_state.policy, pol)` 原子替换整个 policy，4.19 的 `selinux_state.ss` 指向「内核初始化时分配、生命周期与内核相同」的 ss 对象，不能替换。`policy_rwlock` 用于保护 ss 内部数据，替换 ss 会导致锁状态混乱。 | legacy `stop_machine`+`write_lock`（功能正确） |
| **syscall_event_bridge / tp_marker** | dev 的 `syscall_event_bridge.c` 通过 `ksu_syscall_table[orig_nr](regs)` 调用原始 syscall，深度依赖 syscall_table hook（任务 A）。功能上 legacy 的 `hook_manager.c` + `feature/sucompat.c` 已有等效实现（bypass 逻辑在 sucompat.c，process marking 在 hook_manager.c）。tp_marker 拆分是纯代码组织优化。 | `hook_manager.c` 内联实现（功能完整） |
| **throne_tracker 重写（哈希化）** | dev 用 `DEFINE_HASHTABLE(apk_path_hash_list, 8)` + `kref` 引用计数替代 legacy 的线性链表。但 `apk_path_hash_list` 用于缓存已扫描的应用路径，通常 <100 条，链表 O(N) vs 哈希 O(1) 差异微乎其微。Legacy 的 bitmap 快速路径已覆盖 99% 的 uid 查询。 | legacy 线性链表（性能足够） |
| **x86_64/ 下所有文件** | Snapdragon 865 是 ARM64 SoC，x86_64 syscall hook 不适用。 | 不相关 |

---

## 三、🔍 GLM 调研结论（5项，已全部出结论）

```
A: syscall_hook 系列       ████████████████████ 100%  ⚠️ 有限可行，30h+，不推荐
B: rules.c 新架构          ████████████████████ 100%  ❌ 架构不兼容，不可行
C: event_bridge/tp_marker  ████████████████████ 100%  ✅ legacy 已有等效
D: A77 + syscall hook      ████████████████████ 100%  ⚠️ 有风险，sys_call_table 写保护是主因
E: selinux_hide backup     ████████████████████ 100%  ✅ 过滤模式已等效，不升级
```

| 调研 | 结论 | 核心发现 |
|:----:|:----:|---------|
| **A** syscall_hook | ⚠️ 有限可行 | 4.19 有所有必需 API，但 `sys_call_table` 在 rodata 段只读，需要 `set_memory_rw` hack。工作量 30h+，风险高 |
| **B** rules.c | ❌ 不可行 | 4.19 `struct selinux_ss` 与 5.10+ `struct selinux_policy` 架构不兼容。`policydb` 是内嵌字段不是指针，无法 RCU 替换 |
| **C** event_bridge | ✅ 无需移植 | legacy 的 `hook_manager.c` 已有等效实现。拆分纯代码组织优化 |
| **D** A77 | ⚠️ 有风险 | A77 errata 与 syscall hook 无直接关联。主要障碍是 `sys_call_table` 写保护 |
| **E** backup | ✅ 不升级 | 过滤模式（`:ksu:` 字符串检测）与 backup 方案在实际探测场景中完全等效 |

---

## 四、⏳ 待调研/待决策（GLM 已给出建议，可集成）

```
allowlist 哈希化           ████████░░░░░░░░░░░░  40%  保留建议为主，不推荐移植
KSU_VERSION +150           ████████████████████ 100%  已决策：保持现状
sucompat 清理              ██████░░░░░░░░░░░░░░  30%  依赖 syscall_hook
stackprotector             ████████████████████ 100%  已确认：legacy 已有
process marking            ████████████████████ 100%  已确认：legacy 已有
seccomp reset              ████████████████████ 100%  已确认：legacy 已有
umount 隔离修复            ████████████████████ 100%  已确认：legacy 已有
throne OOB 修复            ████████████████████ 100%  已确认：legacy 已有
selinux RCU 修复           ████████████████████ 100%  已确认：legacy 已有
ksu_cred allowlist         ████████████████░░░░  80%  依赖 allowlist 重构，高风险
```

| 功能 | GLM 结论 | 根因分析（源码证据） |
|------|---------|-------------------|
| **allowlist 哈希化** | ❌ 不建议 | dev 的哈希化与 UAPI 版本升级（v3→v4）深度耦合——`current_uid` 重命名为 `curr_uid`、`struct root_profile` 新增 `flags` 字段。必须同步修改 `throne_tracker.c`/`kernel_umount.c`/`sucompat.c`/`setuid_hook.c`/`ksud_integration.c` 共 5+ 文件外加 ksud 用户态。API 从 `bool ksu_get_app_profile(out)` 改为 `ptr = ksu_get_app_profile(uid)` + 调用方必须配对 `ksu_put_app_profile()`。工作量 20-30h。且 legacy 的 bitmap+list 实现在 <100 条记录场景下性能足够。 |
| **KSU_VERSION +150** | ✅ 保持现状 | `+150` 是 legacy 分支的版本补偿机制——legacy 分支提交数比 dev 少，不加 `+150` 计算出的版本号（~33000）会低于 KSU manager app 的最低要求（>=33188）。用户项目的 GHA workflow 已用 `sed -i 's/ccflags-y += -DKSU_VERSION=.*/ccflags-y += -DKSU_VERSION=33188/'` 强制覆盖，`+150` 已无效。删除 `+150` 不影响实际行为，但保留作为安全网。 |
| **sucompat 清理** | ❌ 不移植 | dev 的 sucompat 完全依赖 syscall_table hook——通过 `ksu_syscall_table[orig_nr](regs)` 直接调用原始 syscall。legacy 通过 kprobe 截获，sucompat 只是被 kprobe handler 调用的辅助函数（签名完全不同：dev 用 `ksu_handle_faccessat_sucompat(int orig_nr, const struct pt_regs *regs)`，legacy 用 `ksu_handle_faccessat(int *dfd, const char __user **filename_user, ...)`）。dev 新增的 `is_ksud_exists()` + `override_creds(ksu_cred)` 等功能在 kprobe atomic context 下不可用。 |
| **stackprotector** | ❌ 无需移植 | 任务描述本身就是误解。`dev` 和 legacy 的 `__stack_chk_guard` 代码逐字节相同（都在 `core/init.c` 第 39-70 行），已验证 `diff` 无输出。`__stack_chk_fail` 由内核本身提供（`kernel/panic.c`），不是 KSU 的责任。如果遇到 `undefined reference to __stack_chk_fail`，是内核配置问题，不是缺失代码。 |
| **process marking** | ❌ 不移植 | dev 的 process marking 在 commit e05540f4 中随 syscall_table 重构一同拆分到 `tp_marker.c`。legacy 在 `hook_manager.c` 中内联实现相同的函数（`tracepoint_reg_count`/`ksu_clear_task_tracepoint_flag_if_needed`/`ksu_mark_all_process` 等），功能完全一一对应。拆分是纯代码组织优化，无功能差异。且 dev 的 tp_marker 与 `syscall_hook_manager.c` 深度耦合（用 kretprobe 监听 tracepoint 注册），脱离 syscall_table 后拆分无收益。 |
| **seccomp reset** | ✅ 已在 legacy 中 | legacy `app_profile.c:113` 在 4.19 路径（`LINUX_VERSION_CODE < KERNEL_VERSION(5,9,0)`）正确调用 `put_seccomp_filter(current)`。dev 的改进（`GFP_ATOMIC→GFP_KERNEL` + 统一清理路径）是 5.9+ 的优化，4.19 路径功能等价。 |
| **umount 隔离修复** | ✅ 已在 legacy 中 | legacy `kernel_umount.c` 第 87-106 行的注释已完整说明 6 种 zygote 派生场景的处理逻辑，并调用 `is_zygote(current_cred())` 做隔离进程检测。dev 的 umount 方式不同（用 `ksys_umount`），但 legacy 的 `ksu_sys_umount` + `get_fs/set_fs` 方式在 4.19 上同样正确。 |
| **throne OOB 修复** | ✅ 已在 legacy 中 | `DT_DIR \|\| DT_UNKNOWN` 判断已在 legacy `throne_tracker.c:112-124` 中存在。`apk_path_hash` 分配已用 `GFP_KERNEL`（legacy `throne_tracker.c:152` 原用 `GFP_ATOMIC` 的行已在 legacy 中移除）。 |
| **selinux RCU 修复** | ✅ 无需移植 | dev 用 `rcu_assign_pointer` + `synchronize_rcu` 原子切换 policy。legacy 用 `stop_machine` + `write_lock(policy_rwlock)`。4.19 不能移植 RCU 方式，因为 `struct selinux_ss` 的 `policydb` 是内嵌字段（不是指针），且 `ss` 本身不能替换（生命周期与内核相同）。legacy 的 `stop_machine` 方式虽然"丑陋"，但在 4.19 上功能正确。 |
| **ksu_cred allowlist** | ❌ 不建议 | dev 中 `ksu_cred` 的新增用法（`override_creds(ksu_cred)` 在 faccessat/stat/execve 时切换 cred）是 allowlist 重构 + sucompat 重写的副作用，不是独立功能。legacy 已有 `ksu_cred` 用于 `setup_ksu_cred()` 和 `kernel_umount.c`，功能完整。 |

---

## 五、⚠️ 严重警告

| 级别 | 警告 |
|:----:|------|
| 🔴 **致命** | 不要删除 `compat/kernel_compat.c/.h` — dev 已裁剪 4.x 支持，但 OnePlus 8T 是 Linux 4.19，删除会导致大量符号未定义 |
| 🔴 **致命** | 不要删除 legacy Kbuild 的源码回退补丁块 — 自动给 4.19 内核源码打补丁（can_umount / struct seccomp filter_count / selinux_inode 等） |
| 🟡 **高** | kernel 侧结构体改动必须与 ksud/manager 同步 — UAPI 变更导致 ksud 无法读取 |
| 🟡 **中** | KSU_VERSION `+150` 保持现状 — 用户项目的 sed 强制覆盖为 33188，`+150` 不影响 |
| 🟡 **中** | 始终保留原始 boot.img 与可回退路径 — 每次出包前确认回退流程 |

---

## 七、移植原则

1. **一次只移植一个函数** — 每个功能独立提交，独立测试
2. **所有 bug 必须有根因分析才提交** — 记录到 `ERRORS.md`
3. **提交前 `pre-flight-check` 0 阻断**
4. **每次刷机前备份当前系统 boot 分区**
5. **不追求架构对齐** — 4.19 与 5.10+ 的差异是根本性的，强行对齐会引入 bug
6. **过滤模式优先** — 不需要 backup_sepolicy 等复杂依赖时，用更简单的方案

---

## 七、下一步计划

### 第一阶段：持续维护（当前已稳定）

移植工作**基本完成**，9/9 可移植功能全部实现并通过验证。当前内核已具备：

| 功能类别 | 具体功能 |
|---------|---------|
| 🔒 SELinux 隐藏 | `selinux_hide` 完整版（context+access+setprocattr）+ fake status page |
| 📋 事件日志 | `sulog` + `event_queue`（替代 tiny_sulog） |
| 🔑 权限管理 | `adb_root`、`sucompat`、`kernel_umount` |
| 🛡️ 安全加固 | `remove_avtab_node`、`setuid_hook spin_lock` |
| 🧩 工具链 | `symbol_resolver`、`ksud`（ID=5 支持） |

### 第二阶段：按需升级（无明确需求时不操作）

以下功能 **已调研确认可行但当前不建议移植**，如果未来有明确需求可以重新评估：

| 功能 | 前置条件 | 预估 |
|------|---------|:----:|
| `syscall_hook` 系列（kprobe→syscall_table） | 明确需要避免 atomic context | 30h+ |
| `sucompat` 清理 | syscall_hook 完成后 | 4h |
| `allowlist` 哈希化 | UAPI 变更需同步 ksud | 20-30h |
| `selinux_hide backup` 方案 | 过滤模式被绕过时 | 25h+ |
| `rules.c` RCU 新架构 | 4.19 架构限制解除时 | 16h+ |

### 第三阶段：跨项目经验复用

移植过程中积累的错误经验存储在 `ERRORS.md` 中（E001-E035），涵盖：

| 分类 | 条目数 | 典型教训 |
|:----:|:-----:|---------|
| 注入脚本规范 | 8条 | 锚点匹配、幂等性、路径检查 |
| 4.19 兼容性 | 12条 | `flex_array`、`minmax.h`、`strncpy_from_user` |
| KSU 架构适配 | 7条 | `late_initcall`、`feature_handlers` 清零 |
| selinux_hide 专项 | 5条 | 过滤模式、policydb 不可访问 |
| 跨文件调用 | 3条 | `static` 可见性、extern void* 声明 |

这些经验可用于后续的 KSU-Next 升级或类似的内核移植项目。
