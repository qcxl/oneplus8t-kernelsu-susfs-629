# selinux_hide 完整功能移植 — KernelSU-Next legacy → dev

## 概述

将 dev 分支的 `selinux_hide` **完整功能**（包含 context_write/access_write/setprocattr 劫持 + fake status page）移植到 legacy 分支，让 SELinux 对普通 app 完全隐藏。

## 项目上下文

| 项目 | 值 |
|---|---|
| 设备 | OnePlus 8T (kebab), kernel 4.19.304 |
| KSU | KernelSU-Next **legacy** branch |
| SUSFS | v2.2.0 port (kernel-4.19 branch) |
| 内核源码 | LineageOS 20, commit `5dea892fe7e4` |
| 编译器 | Android clang r450784d |
| CI | GHA workflow at `qcxl/oneplus8t-kernelsu-susfs-629` |

## 现状（已回退到 4804d8b）

Legacy 分支当前只有 **fake status page**（在 `selinux/selinux.c` 中内联实现：`ksu_selinux_hide_status_init/exit`），但缺少完整的 selinux_hide（不劫持 context_write / access_write / setprocattr）。

之前 4 次尝试在 `build-kernelsu-susfs` 仓库中，已全部 revert（详见下方）。

## 架构对比：dev vs legacy

| 特性 | dev 分支 | legacy 分支（当前） |
|---|---|---|
| selinux_hide 位置 | `feature/selinux_hide.c` | 内联在 `selinux/selinux.c` |
| context_write 劫持 | ✅ `ksu_patch_text()` | ❌ 无 |
| access_write 劫持 | ✅ `ksu_patch_text()` | ❌ 无 |
| setprocattr 劫持 | ✅ `ksu_lsm_hook()` | ❌ 无 |
| fake status page | ✅ `my_sel_open_handle_status()` | ✅ 已实现 |
| feature 开关 | ✅ `ksu_register_feature_handler()` | ❌ 无，硬编码开启 |
| backup_sepolicy | ✅ 用于伪造 SELinux 查询 | ✅ 已存在（`selinux/sepolicy.c`） |
| 依赖 ksu_patch_text | ✅ | ❌ hook/patch_memory.h 不存在 |
| 依赖 find_kernel_symbol_exact | ✅ | ❌ infra/symbol_resolver.h 不存在 |
| 依赖 ksu_lsm_hook/unhook | ✅ | ❌ hook/lsm_hook.h 不存在 |

## 需要移植的文件

### 新建文件（从 dev 复制并适配到 legacy）

| 文件 | 来源 URL | 说明 |
|---|---|---|
| `feature/selinux_hide.c` | [dev 分支](https://raw.githubusercontent.com/rifsxd/KernelSU-Next/dev/kernel/feature/selinux_hide.c) | 核心功能，需适配到 4.19 |
| `feature/selinux_hide.h` | [dev 分支](https://raw.githubusercontent.com/rifsxd/KernelSU-Next/dev/kernel/feature/selinux_hide.h) | API 声明 |
| `hook/patch_memory.h` | [dev 分支](https://raw.githubusercontent.com/rifsxd/KernelSU-Next/dev/kernel/hook/patch_memory.h) | 文本补丁基础设施 |
| `infra/symbol_resolver.h` | [dev 分支](https://raw.githubusercontent.com/rifsxd/KernelSU-Next/dev/kernel/infra/symbol_resolver.h) | 符号解析封装 |
| `hook/lsm_hook.h` | [dev 分支](https://raw.githubusercontent.com/rifsxd/KernelSU-Next/dev/kernel/hook/lsm_hook.h) | LSM 钩子替换 API |

### 可能也需要配套实现的文件

| 文件 | 来源 URL | 说明 |
|---|---|---|
| `hook/arm64/patch_memory.c` | [dev 分支](https://raw.githubusercontent.com/rifsxd/KernelSU-Next/dev/kernel/hook/arm64/patch_memory.c) | arm64 实现，含 stop_machine + fixmap |
| `infra/symbol_resolver.c` | dev 分支不存在独立的 .c 文件 | `find_kernel_symbol_exact` 实际实现可能在 `core/` 或 `infra/` 下 |

### 需要修改的文件

| 文件 | 修改内容 |
|---|---|
| `Kbuild` | 添加 `feature/selinux_hide.o`（若独立文件）、更新 ccflags |
| `Kconfig` | 可选：添加 `CONFIG_KSU_SELINUX_HIDE` 开关 |
| `core/init.c` | 将 `ksu_selinux_hide_status_init/exit` 替换为 `ksu_selinux_hide_init/exit` |
| `include/ksu.h` | 确保已包含 `extern struct selinux_policy *backup_sepolicy` |
| `selinux/selinux.c` | 移除内联的 `ksu_selinux_hide_status_*` 函数（由新 `selinux_hide.c` 替代），或者保留并让新文件调用它们 |

## dev 分支 selinux_hide.c 关键函数

| 函数 | 作用 |
|---|---|
| `my_write_context()` | 伪造 `sel_write_context`，对 app 使用 `backup_sepolicy` 返回"假"安全上下文 |
| `my_write_access()` | 伪造 `sel_write_access`，对 app 使用 `backup_sepolicy` 计算假的访问向量决策 |
| `my_setprocattr()` | 伪造 `selinux_setprocattr`，app 改自己的上下文时代替系统策略检查 |
| `my_sel_open_handle_status()` | 伪造 `sel_handle_status_ops.open`，对 app 返回 fake_status page（kernel 4.19 走的路径） |
| `initialize_fake_status()` | 分配新 page，复制真实 `selinux_kernel_status`，修改 enforcing 为 1 |
| `ksu_selinux_hide_enable()` | 调用 `ksu_patch_text()` 替换 context_write / access_write / status_open，调用 `ksu_lsm_hook()` 替换 setprocattr |
| `ksu_selinux_hide_disable()` / `unhook()` | 恢复所有被 patch 的代码 |

## 4.19 兼容性

`selinux_hide.c` 中有两套路径：

```c
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)
    // 使用 backup_sepolicy 的 security_context_to_sid_with_policy()
    // 需要完整的内联副本（string_to_context_struct、avd_init、constraint_expr_eval 等）
#else
    struct selinux_state fake_state;           // <-- 4.19 走这条路径
    fake_state.initialized = true;
    fake_state.policy = backup_sepolicy;
    // 使用 security_context_to_sid(&fake_state, ...)
    // 使用 security_sid_to_context(&fake_state, ...)
    // 使用 security_compute_av_user(&fake_state, ...)
#endif
```

**对于 4.19：** 不需要 `>= 6.6.0` 块内的几百行内联函数副本。使用 `fake_state` 方式即可。

## ksu_patch_text() 的 4.19 兼容性要求

`patch_memory.c` 依赖以下 4.19 特性：
- ✅ `stop_machine()` — 4.19 可用
- ✅ `set_fixmap_offset(FIX_TEXT_POKE0, ...)` — 4.19 可用
- ✅ `clear_fixmap(FIX_TEXT_POKE0)` — 4.19 可用
- ✅ `copy_to_kernel_nofault()` — 4.19 中叫 `probe_kernel_write()`（或检查兼容性）
- ⚠️ `__flush_dcache_area()` — 4.19 可用
- ⚠️ `__flush_icache_range()` — 4.19 可用

需要适配行：
1. `copy_to_kernel_nofault()` → 4.19 用 `probe_kernel_write()` 或 `__copy_to_kernel_nofault()`
2. 确保 `asm/insn.h` 在 4.19 中存在（arm64 4.19 确实有）

## find_kernel_symbol_exact() 的实现

4.19 内核直接调用 `kallsyms_lookup_name()`。简单的实现：

```c
static inline unsigned long find_kernel_symbol_exact(const char *name)
{
    return kallsyms_lookup_name(name);
}
```

## ksu_lsm_hook() 在 4.19 上的实现

`lsm_hook.h` 中的 `KSU_LSM_HOOK_HEADS_TYPE` 宏：

```c
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 12, 0)
#define KSU_LSM_HOOK_HEADS_TYPE struct lsm_static_calls_table
#else
#define KSU_LSM_HOOK_HEADS_TYPE struct security_hook_heads  // <-- 4.19 走这条
#endif
```

`security_hook_heads` 在 4.19 中是一个包含函数指针的结构体。`ksu_lsm_hook()` 的基本操作：
1. 遍历 `security_hook_heads.setprocattr` 链表
2. 找到 `hook->list->hook.setprocattr` 与 `target_name` 匹配的条目
3. 用 `hook->replacement` 替换函数指针
4. 保存原指针到 `hook->original`

⚠️ 注意：legacy 分支已经有 `hook/lsm_hooks.c` 被编译（在 Kbuild 中），但没有配套的头文件。需要检查 `lsm_hooks.c` 中已有的实现或直接用 kprobes 替代。

更简单的**替代方案**：不用 `ksu_lsm_hook()`，改用 kprobes 劫持 `selinux_setprocattr`（4.19 原生支持 kprobes）。但 kprobes 方式有性能开销且可能不稳定。建议：在 `hook/lsm_hooks.c` 基础上补充头文件。

## 修改 init.c

当前 legacy 分支的 `core/init.c` 中已有：

```c
extern void ksu_selinux_hide_status_init(void);
extern void ksu_selinux_hide_status_exit(void);
extern void ksu_selinux_hide_status_handle_second_stage(void);
extern void ksu_selinux_hide_status_handle_post_fs_data(void);
```

需要改为：

```c
#include "feature/selinux_hide.h"
```

并将调用替换为：
- `ksu_selinux_hide_status_init()` → `ksu_selinux_hide_init()`
- `ksu_selinux_hide_status_exit()` → `ksu_selinux_hide_exit()`（在 `kernelsu_exit` 中，当前 legacy 没有调用 exit）

同时注意：legacy 分支的 `init.c` 在 `kernelsu_init()` 中没有调用 `ksu_selinux_hide_status_exit()`，需要在 `kernelsu_exit()` 添加。

## 修改 Kbuild

当前 legacy Kbuild 中已有：
```
kernelsu-objs += selinux/selinux.o
kernelsu-objs += selinux/rules.o
kernelsu-objs += selinux/sepolicy.o
```

新增：
```
kernelsu-objs += feature/selinux_hide.o
```

ccflags 中已有 SELinux 头文件路径：
```
ccflags-y += -I$(srctree)/security/selinux -I$(srctree)/security/selinux/include
ccflags-y += -I$(objtree)/security/selinux
```

## 修改 Kconfig

可选：新增 `CONFIG_KSU_SELINUX_HIDE` 配置项：

```
config KSU_SELINUX_HIDE
    bool "SELinux hide feature"
    depends on KSU
    default y
```

## GHA workflow 集成

需要在 `qcxl/oneplus8t-kernelsu-susfs-629` 的 workflow 中添加：

1. `fix-ksu-uapi-v2.py`（已存在，修正 UAPI 版本不匹配）
2. **新增步骤**：`Inject selinux_hide (from dev branch)` — 用 Python 脚本将 `selinux_hide.c`、`patch_memory.h`、`patch_memory.c`、`symbol_resolver.h`、`lsm_hook.h` 注入到 legacy 内核树中，并更新 init.c / Kbuild

参考现有的 `inject-susfs-dispatch.py` 模式，创建 `inject-selinux-hide.py`。

## 先前失败记录（build-kernelsu-susfs 仓库）

| 提交 | 内容 | 失败原因 |
|---|---|---|
| `47a1a4e` | 首次移植完整版 selinux_hide | Kbuild 锚点不对，编译失败 |
| `aa4f796` | 修复 Kbuild 锚点 + 删除冲突代码 | 编译过了，但链接阶段缺 `hook/patch_memory.h` 等 |
| `55b86fa` | 改用 `kallsyms_lookup_name` 替代 `find_kernel_symbol_exact` | 依然缺 `ksu_patch_text()` 依赖的文本补丁基础设施 |
| `62d0d0a` | Revert | 全面回退到 4804d8b |

核心教训：
- **不能只导入 selinux_hide.c**，它的依赖链很深：`selinux_hide.c → patch_memory.h → patch_memory.c(arm64)` + `symbol_resolver.h` + `lsm_hook.h`
- `ksu_patch_text()` 是文本补丁的核心，arm64 实现依赖 `stop_machine` + fixmap，这些 4.19 都支持，但 header 包含路径和函数名需要适配

## 移植方法建议

### 方法 A（推荐）：全量基础设施移植

1. 复制 `selinux_hide.c` + `selinux_hide.h` → `feature/`
2. 复制 `patch_memory.h` → `hook/`
3. 复制 `patch_memory.c` → `hook/arm64/`（需适配 `copy_to_kernel_nofault` → 4.19 兼容）
4. 创建 `infra/symbol_resolver.h`（简单封装 `kallsyms_lookup_name`）
5. 复制 `lsm_hook.h` → `hook/`（需确认与 `hook/lsm_hooks.c` 兼容）
6. 修改 `init.c`：更换调用名、添加 `#include`
7. 修改 `Kbuild`：添加 `.o`
8. 修改 `Kconfig`：添加配置项
9. 修改 `selinux/selinux.c`：移除或适配内联的 `ksu_selinux_hide_status_*` 函数

### 方法 B（简化）：仅 import 关键文件，原地改造

1. 只在 `feature/` 下创建 `selinux_hide.c`，将 `patch_memory.h`、`lsm_hook.h` 的代码直接内联到 `.c` 文件头部
2. `find_kernel_symbol_exact` → 直接用 `kallsyms_lookup_name`
3. 用直接赋值替代 `ksu_patch_text()`（对于 `write_op` 和 `sel_handle_status_ops`，它们是指针数组/结构体，不需要文本补丁）
4. 用 kprobes 替代 `ksu_lsm_hook()`

**方法 B 更简单且对 4.19 更友好**，因为 `write_op` 和 `sel_handle_status_ops` 是内存中的指针，不需要 `stop_machine`。缺点是 dev 分支升级时需要手动跟进。

## 参考 URL 汇总

| 文件 | legacy 分支 | dev 分支 |
|---|---|---|
| `selinux/selinux.c` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/selinux/selinux.c) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/selinux/selinux.c) |
| `selinux/sepolicy.c` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/selinux/sepolicy.c) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/selinux/sepolicy.c) |
| `selinux/rules.c` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/selinux/rules.c) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/selinux/rules.c) |
| `core/init.c` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/core/init.c) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/core/init.c) |
| `include/ksu.h` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/include/ksu.h) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/include/ksu.h) |
| `policy/feature.h` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/policy/feature.h) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/policy/feature.h) |
| `Kbuild` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/Kbuild) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/Kbuild) |
| `Kconfig` | [链接](https://github.com/rifsxd/KernelSU-Next/blob/legacy/kernel/Kconfig) | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/Kconfig) |
| `feature/selinux_hide.c` | **不存在** | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/feature/selinux_hide.c) |
| `feature/selinux_hide.h` | **不存在** | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/feature/selinux_hide.h) |
| `hook/patch_memory.h` | **不存在** | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/hook/patch_memory.h) |
| `hook/arm64/patch_memory.c` | **不存在** | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/hook/arm64/patch_memory.c) |
| `infra/symbol_resolver.h` | **不存在** | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/infra/symbol_resolver.h) |
| `hook/lsm_hook.h` | **不存在** | [链接](https://github.com/rifsxd/KernelSU-Next/blob/dev/kernel/hook/lsm_hook.h) |

## CI 仓库

- **Kernel CI**: `https://github.com/qcxl/oneplus8t-kernelsu-susfs-629`
- **KSU Manager APK**: `https://github.com/qcxl/KernelSU-Next`
- **Workflow 文件**: `build-kernelsu-susfs/.github/workflows/build-ksu-debug.yml`
- **注入脚本目录**: `build-kernelsu-susfs/scripts/`（参考 `inject-susfs-dispatch.py` 的模式）
- **内核 patches 目录**: `build-kernelsu-susfs/kernel-patches/`
- **已存在的 inject 脚本**: `inject-susfs-dispatch.py`, `inject-susfs-sus-map.py`, `inject-v2-features-batch1.py`, `inject-v2-features-batch2.py`, `apply-ksu-hooks.py`

## 关键注意事项

1. `write_op` 符号在 4.19 内核中的名称和索引值需确认——`enum sel_inos` 的枚举值与 `selinuxfs.c` 中的定义必须完全匹配，否则会 hook 到错误的写入操作
2. `sel_handle_status_ops` 在 4.19 内核中是否存在需确认，如果不存在，fake status page 可能无法工作
3. fake status 的初始化时机：legacy 分支中 `ksu_selinux_hide_status_init` 在 `kernelsu_init()` 中调用，需要确认 `selinux_state.status_page` 在那个时间点已经分配
4. `backup_sepolicy` 在 `selinux/sepolicy.c` 中创建，legacy 分支中通过 `apply_kernelsu_rules()` 初始化——该函数在 `ksu_late_loaded` 时调用。对于非 late_load 模式，需要确认何时创建
5. 4.19 的 `<security.h>` 包含路径：需要在 Kbuild 的 ccflags 中加 `-I$(srctree)/security/selinux -I$(srctree)/security/selinux/include`
6. 要特别注意 `selinux_hide.c` 中的 `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)` 块——4.19 走 `#else` 路径，`fake_state` 方式无需那几百行内联函数副本
