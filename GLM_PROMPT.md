# GLM 5.2 移植任务 — KernelSU-Next dev → legacy（4.19）

## 你的任务

你是一个内核移植专家。请阅读以下项目背景，理解 dev 分支的功能代码后，**生成可直接使用的 C 源码文件 + Python 注入脚本**，供我集成到项目仓库中。

**不要尝试修改 GitHub 仓库**，你只需要生成完整的代码文件给我即可。

---

## 项目概况

将 KernelSU-Next **dev 分支**的功能移植到 **legacy 分支**（OnePlus 8T "kebab"，Linux 4.19.304）。

| 项目 | 地址 |
|------|------|
| 我的项目仓库 | https://github.com/qcxl/oneplus8t-kernelsu-susfs-629 |
| KSU-Next（dev，功能源） | https://github.com/KernelSU-Next/KernelSU-Next/tree/dev/kernel |
| KSU-Next（legacy，移植目标） | https://github.com/KernelSU-Next/KernelSU-Next/tree/legacy/kernel |

---

## 移植架构

所有 KSU 内核代码最终通过符号链接 `drivers/kernelsu/ → KernelSU-Next/kernel/` 定位。GHA 构建时运行 Python 注入脚本，将 `kernel-patches/` 目录下的源文件复制到 `drivers/kernelsu/` 下的对应位置。

**注入脚本模式参考**（这是我已完成的一个注入脚本，请按此模式编写）：

```python
#!/usr/bin/env python3
"""inject-xxx.py — 描述"""
import sys, os
KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")
SCRIPT_MARK = "/* KSU_XXX_INJECTED */"

def inject(filepath, anchor, snippet, after=True):
    fp = filepath
    if not os.path.exists(fp): print(f"  ERROR: {fp} not found"); return False
    with open(fp) as f: c = f.read()
    if SCRIPT_MARK in c: print(f"  SKIP: {fp} already injected"); return True
    if anchor not in c: print(f"  ERROR: anchor not found in {fp}"); return False
    block = "\n" + SCRIPT_MARK + "\n" + snippet.strip() + "\n"
    c = c.replace(anchor, (anchor + block) if after else (block + anchor), 1)
    with open(fp, 'w') as f: f.write(c)
    print(f"  OK: {fp}")
    return True
```

**源文件模式参考**：将完整的 .c/.h 文件放到 `kernel-patches/feature/xxx.c`，注入脚本用 `shutil.copy2()` 复制到 `drivers/kernelsu/feature/xxx.c`。

---

## 4.19 关键差异（与 dev 的 5.10+ 不同）

| dev 使用的 API | 4.19 替代方案 | 说明 |
|---------------|-------------|------|
| `find_kernel_symbol_exact()` | `kallsyms_lookup_name()` | 4.19 仍有 `EXPORT_SYMBOL` |
| `ksu_patch_text()` | 直接指针赋值 或 `set_memory_rw/set_memory_ro` | `write_op[]` 在 4.19 是普通 data 段，已验证可直接赋值 |
| `ksu_lsm_hook()` | hlist 遍历 `security_hook_heads` | 已验证可行 |
| `struct selinux_policy` | `struct selinux_ss` | 5.10 才合并，4.19 用 ss |
| `copy_to_kernel_nofault()` | 不存在，需替代 | — |
| `strncpy_from_user_nofault()` | `strncpy_from_user()` | 4.19 没有 `_nofault` 变体 |
| `<linux/minmax.h>` | `<linux/kernel.h>` | minmax.h 是 5.1+ 新增 |
| `user_stack_pointer(regs)` | `PT_REGS_SP(regs)` | KSU 的 arch.h 定义了 `PT_REGS_SP` |
| `policydb_init()` | **不存在**（static 函数） | 不要调用，`policydb_read()` 内部会调用 |

---

## 我已完成的移植（供参考，不需要重新实现）

| 功能 | 做法简述 |
|------|---------|
| selinux_hide（完整版） | 新建 `feature/selinux_hide.c`，过滤模式（`:ksu:` 字符串检测），`write_op[]` 直接赋值，`security_hook_heads` 遍历 |
| sulog | 从 dev 复制 `sulog/event.c/fd.c` + `feature/sulog.c`，`strncpy_from_user_nofault→strncpy_from_user`，`minmax.h→kernel.h`，`late_initcall` |
| adb_root | 从 dev 复制 `feature/adb_root.c`，`user_stack_pointer→PT_REGS_SP`，`transive_to_domain(KERNEL_SU_CONTEXT, cred, true)` 去掉第 3 个参数，注入 + 添加 escape_to_root_for_adb_root 到 selinux.c，添加声明到 selinux.h，添加 kprobe 钩子调用 |

---

## 待移植功能（请逐个生成代码）

### 任务 1：ksu_cred allowlist

**说明**：改用 `ksu_cred` 保存 allowlist，提升一致性与安全性。dev 和 legacy 各有自己的 allowlist 实现，需要对比取差异。

**操作步骤**：
1. 阅读 dev 的 `kernel/policy/allowlist.c` 和 legacy 的 `kernel/policy/allowlist.c`
2. 识别 dev 中 `ksu_cred` 相关的改动逻辑
3. 生成注入脚本 `scripts/inject-ksu-cred.py`，将 dev 的改进逻辑注入到 legacy 的 allowlist.c 中
4. 注意 include 路径差异：dev 用 `#include "manager/app_profile.h"`，legacy 用 `#include "app_profile.h"`

**产出要求**：
- 完整的 `scripts/inject-ksu-cred.py`
- 如果涉及新文件，提供 `kernel-patches/xxx`

### 任务 2：stackprotector

**说明**：提供自有 `__stack_chk_guard`/`__stack_chk_fail`，解决链接期 undefined reference。

**操作步骤**：
1. 阅读 dev 的 `kernel/infra/stackprotect.c` 和 `kernel/infra/stackprotect.h`
2. 复制到 `kernel-patches/infra/stackprotect.c` 和 `kernel-patches/infra/stackprotect.h`
3. 生成注入脚本，复制文件 + 更新 Kbuild 添加 `infra/stackprotect.o`

**产出要求**：
- `kernel-patches/infra/stackprotect.c`
- `kernel-patches/infra/stackprotect.h`
- `scripts/inject-stackprotect.py`

### 任务 3：process marking

**说明**：修复 built-in 模式下进程标记逻辑，确保 root 授权判定正确。

**操作步骤**：
1. `diff dev/kernel/core/init.c legacy/kernel/core/init.c` 找出进程标记相关差异
2. 生成注入脚本修改 legacy 的 `core/init.c`

**产出要求**：`scripts/inject-process-marking.py`

### 任务 4：allowlist 哈希化

**说明**：数据结构优化，`HASHTABLE`+`kref` 替代 `LIST_HEAD`。

**操作步骤**：
1. `diff dev/kernel/policy/allowlist.c legacy/kernel/policy/allowlist.c`
2. 识别哈希化相关代码段
3. 生成注入脚本

**产出要求**：`scripts/inject-allowlist-hash.py`

### 任务 5：sepolicy 动态清理（remove_avtab_node）

**说明**：新增 `remove_avtab_node` 函数，用于动态清理 SELinux 策略规则。

**操作步骤**：
1. 在 dev 的 `kernel/selinux/sepolicy.c` 中找到 `remove_avtab_node` 函数
2. 这是独立的 30 行函数，将其注入到 legacy 的 sepolicy.c

**产出要求**：`scripts/inject-remove-avtab.py`

### 任务 6：KSU_VERSION +150 决策

**说明**：legacy 的 `KSU_VERSION = 30000 + git_version + 150`，dev 去掉了 `+150`。需确认方案。

**操作步骤**：
1. 对比 dev 和 legacy 的 `Kbuild` 中版本计算逻辑
2. 给出建议方案

**产出要求**：简要分析和建议

### 任务 7：sucompat 清理

**说明**：清理 legacy 中 compat 兼容代码。

**操作步骤**：
1. `diff dev/kernel/feature/sucompat.c legacy/kernel/feature/sucompat.c`
2. 注意 include 路径差异（dev 用相对路径，legacy 可能需要 compat 前缀）
3. 生成注入脚本清理 legacy

**产出要求**：`scripts/inject-sucompat-clean.py`

### 任务 8：setuid_hook 简化

**说明**：同步 dev 的 `ksu_install_fd` 方式替代 legacy 的 `task_work` 延迟。

**操作步骤**：
1. `diff dev/kernel/hook/setuid_hook.c legacy/kernel/hook/setuid_hook.c`
2. 生成注入脚本

### 任务 9：setuid_hook 简化

**说明**：同步 dev 的 `ksu_install_fd` 方式替代 legacy 的 `task_work` 延迟。

**操作步骤**：
1. `diff dev/kernel/hook/setuid_hook.c legacy/kernel/hook/setuid_hook.c`
2. 生成注入脚本

**产出要求**：`scripts/inject-setuid-hook.py`

---

## 待调研功能（请阅读源码后给出可行性评估和移植方案）

以下功能之前标记为"跳过"，**现在请你重新调研**，阅读 dev 和 legacy 的源码后给出详细的可行性评估，如果可行则提供移植方案和代码。

### 调研任务 A：syscall_hook 系列

**文件**：`hook/syscall_hook*.c/h`、`hook/hook_manager.c`、`hook/syscall_event_bridge.c`

**背景**：dev 用 `sys_call_table` 直接截获，legacy 用 kprobe 方式。4.19 的 ARM64 上 `sys_call_table` 是否可写？CFI 是否开启？Cortex-A77 是否有已知兼容问题？

**调研要求**：
1. 阅读 dev 的 `hook/syscall_hook*.c` 和 legacy 的 `hook/hook_manager.c`
2. 评估 4.19 ARM64 上 `sys_call_table` 可写性
3. 评估移植工作量（预计 12h+ 是否合理）
4. 给出结论：**可行 / 有限可行 / 不可行**，附源码证据

**如果可行**：提供移植代码和注入脚本

### 调研任务 B：rules.c 策略新架构

**文件**：`selinux/rules.c`

**背景**：dev 用 `dup_sepolicy`+`rcu_assign` 原子切换，legacy 用 `stop_machine`+`policy_rwlock`。4.19 上 `rcu_assign_pointer` 是否可用？

**调研要求**：
1. 对比 dev 和 legacy 的 rules.c
2. 评估 4.19 使用 `rcu_assign_pointer` 的可行性
3. 评估 `stop_machine` 方式在 4.19 上的正确性
4. 给出结论及移植方案

### 调研任务 C：syscall_event_bridge / tp_marker

**文件**：`hook/syscall_event_bridge.c`、`hook/tp_marker.c`

**背景**：依赖新钩子基础设施。4.19 上 tracepoint 机制是否完全可用？

**调研要求**：
1. 阅读 dev 的实现
2. 评估 4.19 兼容性
3. 给出结论

### 调研任务 D：arm64 内联 syscall hook

**文件**：`hook/arm64/syscall_hook.c`

**背景**：v1.1.1 hotfix 因 Cortex-A77 CPU 上的 su 兼容问题将 syscall hook 回退。OnePlus 8T 使用 Cortex-A77。

**调研要求**：
1. 阅读相关代码和提交历史
2. 确认 Cortex-A77 上内联 syscall hook 的具体问题
3. 评估是否有修复方案
4. 给出结论

### 调研任务 E：selinux_hide Route B（backup 方案）

**背景**：当前已用过滤模式（`:ksu:` 字符串检测）实现了 context/access 隐藏。过滤模式与 dev 的 backup 方案在功能上等效。

**调研要求**：
1. 对比过滤模式和 backup 模式的优劣势
2. 分析备份方案中 `policydb_*` 函数在 4.19 上的可访问性（注意 `policydb_init` 是 static 函数）
3. 评估是否有必要升级到 backup 方案
4. 给出结论

---

## 代码产出规范

1. **每个功能独立产出**：一个功能一个注入脚本，不要合并
2. **文件路径**：所有路径相对于项目根目录
3. **注入脚本**：锚点用稳定字符串（函数签名、独特注释行），不要用空格/tab 缩进做匹配
4. **Kbuild 更新**：需要添加新 .o 文件时，在脚本中用字符串替换
5. **Kconfig**：需要添加新配置项时，修改 `kernel-patches/ksu.config`
6. **uapi/feature.h**：需要添加新 Feature ID 时，注意 legacy 已有 `KSU_FEATURE_SELINUX_HIDE_STATUS = 4`
7. **幂等性**：每次注入用唯一 `/* KSU_XXX_INJECTED */` 标记检查
8. **4.19 兼容**：上面表格中的 4.19 差异必须处理
9. **底线规则**（**绝对不要违反**）：
   - 不要删除 `compat/kernel_compat.c/.h` — dev 已裁剪 4.x 支持，但 4.19 需要它
   - 不要删除 legacy Kbuild 的源码回退补丁块

## 输出格式

每个任务请给出：

```c
// ====== kernel-patches/feature/xxx.c ======
// (完整文件内容)
```

```python
// ====== scripts/inject-xxx.py ======
// (完整注入脚本)
```

以及简要说明改动逻辑和风险点。
