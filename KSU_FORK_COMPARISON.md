# KernelSU-Next dev → legacy 移植进度总表

> 最后更新: 2026-07-04 | 基于源码全量对比 + GLM 5.2 MAX 报告交叉验证 + 实机验证
> dev: `8c363a1` | legacy: `77b3027` | 设备: OnePlus 8T (kebab), kernel 4.19.304

---

## 🎯 总体进度

```
移植完成度:     ████████████████████░░░░░░░░░░  43%  (9/21)
调研完成度:     ██████████████████████████████ 100%  (5/5)
```

| 分类 | 总计 | ✅ 完成 | ⏳ 进行 | ❌ 阻塞 | ⬜ 跳过 |
|:----|:---:|:------:|:------:|:------:|:------:|
| 🟢 已移植 | 24项 | **9** | 0 | 0 | 15 |
| 🔴 不可移植 | 5项 | — | — | **2** | **3** |
| 🔍 需调研 | 5项 | **5**已出结论 | 0 | 0 | 0 |

---

## 一、✅ 已完成移植（9项）

```
selinux_hide (GLM完整版)    ████████████████████ 100%  context+access+setprocattr
sulog                      ████████████████████ 100%  替代 tiny_sulog
adb_root                   ████████████████████ 100%  execve 劫持 + LD_PRELOAD
event_queue                ████████████████████ 100%  通用事件队列
symbol_resolver            ████████████████████ 100%  kallsyms_lookup_name 封装
ksud 交叉编译              ████████████████████ 100%  支持 ID=5 toggle
remove_avtab_node          ████████████████████ 100%  GLM生成，待验证
setuid_hook spin_lock      ████████████████████ 100%  GLM生成，待验证
GLM_PROMPT                 ████████████████████ 100%  后续任务说明文档
```

| 功能 | 说明 | 工作量 | 提交/来源 |
|------|------|:------:|-----------|
| **selinux_hide（GLM 完整版）** | 过滤模式（`:ksu:` 字符串检测），context_write + access_write + setprocattr 三个钩子，`write_op[]` 直接赋值，`security_hook_heads` hlist 遍历 | 🔴 25h | `e904f34` |
| **sulog 子系统** | 完整 event_queue + sulog event/fd 实现，替代 `tiny_sulog`。4.19 兼容：`strncpy_from_user_nofault→strncpy_from_user`，`minmax.h→kernel.h` | 🟢 8h | `6dbf6f4` + `c092fdd` + `061ec8d` |
| **adb_root** | execve 劫持注入 LD_PRELOAD。4.19 兼容：`user_stack_pointer→PT_REGS_SP`，`transive_to_domain` 2参数 | 🟡 4h | `73b57c5` + `265648f` + `932facc` |
| **event_queue** | 通用事件队列（spinlock + waitqueue + list），sulog 的基础依赖 | 🟢 2h | `6dbf6f4` |
| **symbol_resolver** | 简化版，仅 `kallsyms_lookup_name` 封装 | 🟢 2h | `241ae4b` |
| **ksud 交叉编译** | 本地编译支持 ID=5 (`SelinuxHideNew = 5`) 的 ksud，推送到设备 | 🟡 4h | `2be9479` + 本地编译 |
| **remove_avtab_node** | 冗余 avtab 节点自动清理（GLM 生成，已验证语法） | 🟢 30min | `fab6acf` |
| **setuid_hook spin_lock** | 添加 spin_lock_irq 保护（GLM 生成，已验证语法） | 🟢 30min | `fab6acf` |
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
| **selinux_hide Route B（backup）** | `policydb_*` 是 SELinux SS 内部函数，`security/selinux/ss/policydb.h` 不可从 KSU 访问。`policydb_init` 是 `static` 函数 | 过滤模式（已完成） |
| **patch_memory arm64** | dev 用于修改只读代码页。4.19 无 `copy_to_kernel_nofault`/`set_fixmap` 完整栈 | `write_op[]` 直接赋值（已验证） |
| **lsm_hook 完整版** | 依赖 `patch_memory` 和 6.6+ 静态调用 | hlist 遍历 `security_hook_heads`（已验证） |
| **syscall_hook arm64 完整版** | `sys_call_table` 在 rodata 段只读，需 `set_memory_rw` hack。Cortex-A77 有历史回退记录。工作量 30h+ | legacy kprobe 方式可用 |
| **rules.c 策略新架构** | `struct selinux_ss`（4.19）与 `struct selinux_policy`（5.10+）架构不兼容，`rcu_assign_pointer` 不能替换 ss | legacy `stop_machine` + `policy_rwlock` 方式正确 |
| **syscall_event_bridge / tp_marker** | 依赖 syscall_table hook（任务 A）。legacy 已有等效实现 | legacy `hook_manager.c` 内联实现 |
| **throne_tracker 重写** | 纯性能优化（哈希加速），legacy 版本功能等价 | legacy 版本 |
| **x86_64/ 下所有文件** | 设备为 ARM64 | 不相关 |

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

| 功能 | GLM 结论 | 建议 |
|------|---------|------|
| **allowlist 哈希化** | ❌ 不建议 | UAPI 变更（v3→v4），需要改 5+ 个调用方 + ksud 用户态。工作量 20-30h。保留 legacy bitmap+list 实现 |
| **KSU_VERSION +150** | ✅ 保持现状 | `+150` 是 legacy 的安全补偿。用户项目已用 sed 强制覆盖为 33188，`+150` 不影响实际行为 |
| **sucompat 清理** | ❌ 不移植 | 依赖 syscall_table hook（任务 A），不可独立移植。legacy 功能完整 |
| **stackprotector** | ❌ 无需移植 | dev 和 legacy 代码逐字节相同，都是内联在 `core/init.c` 中 |
| **process marking** | ❌ 不移植 | dev 拆分到 `tp_marker.c` 是代码组织优化，legacy 内联在 `hook_manager.c` 中等效 |
| **seccomp reset** | ✅ 已在 legacy 中 | legacy 4.19 路径正确走 `put_seccomp_filter(current)` |
| **umount 隔离修复** | ✅ 已在 legacy 中 | `is_zygote` 逻辑和隔离进程处理已在 legacy `kernel_umount.c` 中 |
| **throne OOB 修复** | ✅ 已在 legacy 中 | `DT_DIR \|\| DT_UNKNOWN` 和 `GFP_KERNEL` 已在 legacy `throne_tracker.c` 中 |
| **selinux RCU 修复** | ✅ 无需移植 | legacy 用 `stop_machine` + `policy_rwlock` 是 4.19 正确做法 |
| **ksu_cred allowlist** | ❌ 不建议 | 是 allowlist 重构的副作用，不可独立移植。legacy 的 `ksu_cred` 用法已足够 |

---

## 五、📦 待集成代码（GLM 已生成，可直接用）

| 文件 | 来源 | 说明 | 状态 |
|------|------|------|:----:|
| `scripts/inject-remove-avtab.py` | GLM 5.2 | 冗余 avtab 节点自动清理，30 行独立函数 | ✅ 已提交 `fab6acf` |
| `scripts/inject-setuid-hook.py` | GLM 5.2 | setuid_hook 添加 spin_lock_irq 保护 | ✅ 已提交 `fab6acf` |

---

## 六、⚠️ 严重警告

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
