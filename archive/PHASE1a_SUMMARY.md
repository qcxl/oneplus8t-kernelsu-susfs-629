# OnePlus 8T (kebab) KernelSU + SUSFS 内核编译项目 —— 阶段性总结文档

> 撰写日期：2026-06-30  
> 项目阶段：Phase 1a（KernelSU-Next legacy + SUSFS v1.5.5）  
> 目标设备：OnePlus 8T (kebab) / LineageOS 20 / Android 13 / Kernel 4.19.304  
> 项目仓库：https://github.com/qcxl/oneplus8t-kernelsu-susfs-629

---

## 目录

1. [项目概述](#1-项目概述)
2. [已完成工作](#2-已完成工作)
3. [技术架构与决策](#3-技术架构与决策)
4. [遇到的问题及解决](#4-遇到的问题及解决)
5. [排查与修复中的错误复盘](#5-排查与修复中的错误复盘)
6. [参考资料与技术借鉴](#6-参考资料与技术借鉴)
7. [经验与收获](#7-经验与收获)
8. [后续计划](#8-后续计划)
9. [文件清单与作用](#9-文件清单与作用)

---

## 1. 项目概述

### 1.1 项目目标

为 OnePlus 8T（kebab）编译一个可启动的内核，集成：
- **KernelSU-Next legacy**（非 GKI 4.19 内核的 root 方案）
- **SUSFS v1.5.5**（KernelSU 的 root 隐藏插件，通过 kernel-4.19 分支获取）
- **调试支持**（pstore/ramoops、initcall_debug 等）

### 1.2 技术栈

| 组件 | 选择 | 原因 |
|------|------|------|
| 内核源码 | LineageOS/android_kernel_oneplus_sm8250 @ 5dea892fe7e4 | OnePlus 8T 官方 LOS 20 内核 |
| KernelSU | rifsxd/KernelSU-Next legacy 分支 | 专为 non-GKI 设计，支持手动 hook |
| SUSFS | simonpunk/susfs4ksu kernel-4.19 分支 | v1.5.5，官方支持的 4.19 版本 |
| 编译工具链 | Android clang r450784d | 与 LineageOS 官方一致 |
| CI | GitHub Actions (ubuntu:20.04 容器) | 自动化构建与验证 |
| 验证方式 | fastboot boot（临时启动，不刷写） | 安全验证内核可用性 |

### 1.3 关键约束

- **Non-GKI 平台**（Qualcomm sm8250/kona，kernel 4.19）：kprobe hook 会导致启动崩溃
- **必须使用 Manual Hook**（`CONFIG_KSU_MANUAL_HOOK=y`）
- **ramoops/pstore 不可用**（sm8250 DDR 掉电清空）：依赖构建-测试循环
- **SUSFS v1.5.5 为基线**：v2.x 特性暂不移植

---

## 2. 已完成工作

### 2.1 基础设施搭建 ✅

| 工作项 | 说明 | 状态 |
|--------|------|------|
| GHA CI 工作流 | `.github/workflows/build-ksu-debug.yml` | ✅ 稳定运行 |
| Docker 构建环境 | ubuntu:20.04 + clang-r450784d | ✅ |
| boot.img 打包脚本 | `build-boot-img.py`（支持 `--append-cmdline`） | ✅ 修复过 2 个 bug |
| 调试内核配置 | `debug.config`（pstore/ramoops + initcall_debug） | ✅ |

### 2.2 内核编译与验证 ✅

| 工作项 | 说明 | 状态 |
|--------|------|------|
| 纯 KSU 内核（无 SUSFS） | 首次验证 KSU 可启动 | ✅ 已验证 |
| KSU + SUSFS v1.5.5 | Phase 1a 目标 | ✅ 已验证 |
| fastboot boot 启动 | 临时启动验证 | ✅ |
| dmesg 确认 susfs_init | 日志中确认 SUSFS v1.5.5 初始化 | ✅ |
| kallsyms 符号隐藏 | CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS 生效 | ✅ |
| mountinfo 无痕迹 | /proc/self/mountinfo 干净 | ✅ |

### 2.3 关键脚本与补丁 ✅

| 文件 | 功能 | 状态 |
|------|------|------|
| `scripts/apply-ksu-hooks.py` | 在 VFS 文件中注入 KSU 手动 hook | ✅ 稳定 |
| `scripts/inject-susfs-dispatch.py` | 在 KSUN legacy 中注入 SUSFS ioctl dispatch | ✅ 经过多次迭代 |
| `kernel-patches/susfs_stubs.c` | 为 50_add patch 引用的跨模块符号提供 stub | ✅ |
| `kernel-patches/ksu.config` | KSU + SUSFS Kconfig 配置片段 | ✅ |
| `kernel-patches/debug.config` | 调试选项（ramoops/printk 等） | ✅ |

---

## 3. 技术架构与决策

### 3.1 架构总览

```
┌─────────────────────┐     ioctl(fd, 0x55, ...)     ┌──────────────────────────┐
│   ksu_susfs 用户态   │ ──────────────────────────▶  │ KSUN legacy dispatch.c   │
│   (WebUI / service)  │     KSU_IOCTL_SUSFS          │ ksu_ioctl_handlers[]     │
└─────────────────────┘                               └──────────┬───────────────┘
                                                                  │ do_susfs_ioctl()
                                                                  ▼
                                                    ┌──────────────────────────┐
                                                    │ fs/susfs.c  (SUSFS 核心) │
                                                    │ 维护隐藏路径/挂载/kstat  │
                                                    │ 列表                     │
                                                    └──────────┬───────────────┘
                                                                 │ VFS hook 点
                    ┌─────────────────────────────────────────────┼─────────────────────────┐
                    ▼                                             ▼                         ▼
          ┌──────────────────┐                        ┌──────────────────┐      ┌──────────────────┐
          │ __d_path         │                        │ show_mountinfo   │      │ generic_fillattr │
          │ (SUS_PATH)       │                        │ (SUS_MOUNT)      │      │ (SUS_KSTAT)      │
          └──────────────────┘                        └──────────────────┘      └──────────────────┘
```

### 3.2 关键决策点

#### 决策 1：KernelSU 分支选择
- **选择**：rifsxd/KernelSU-Next legacy 分支
- **原因**：tiann/KernelSU 主线 v1.0+ 不再支持 non-GKI；KernelSU-Next legacy 分支在 Kconfig 中默认启用 `KSU_MANUAL_HOOK`（当 `!KPROBES` 时）
- **代价**：KSUN legacy 使用 ioctl 派发表架构，与传统 KernelSU 的 prctl 通道完全不同，需要重写 dispatch 注入逻辑

#### 决策 2：SUSFS 版本选择
- **选择**：v1.5.5（kernel-4.19 分支 HEAD）
- **原因**：v2.x（SUSFS 主分支）需要 kernel 5.10+，4.19 不可用
- **增量升级路径**：官方 kernel-4.19 分支提供 v1.5.x 特性集 → 未来从 sidex15 4.14 backport 中前向移植 v2.x 特性

#### 决策 3：用户态通信通道
- **选择**：KSUN legacy 的 ioctl（通过匿名 inode fd）
- **原因**：KSUN legacy 不使用传统 KernelSU 的 prctl 通道，改用 ioctl 派发表
- **影响**：SUSFS 用户态工具（ksu_susfs）需要使用 ioctl 而非 prctl 与内核通信

#### 决策 4：Hook 方式
- **选择**：Manual Hook（`CONFIG_KSU_MANUAL_HOOK=y`），禁用 kprobes
- **原因**：4.19 non-GKI 上 kprobe 不稳定，启动必崩

---

## 4. 遇到的问题及解决

### 4.1 构建流程问题

#### 问题 1：Kconfig 未注册 → SUSFS 未被编译

**现象**：构建成功，但 `config.txt` 中没有 `CONFIG_KSU_SUSFS_*` 选项，编译产物不含任何 susfs 符号。

**产生原因**：`merge_config.sh` 处理 ksu.config 时，`CONFIG_KSU_SUSFS` 等符号在 Kconfig 树中不存在，被静默丢弃。root cause：`10_enable_susfs_for_ksu.patch` 是为旧版 KernelSU 的 `KernelSU/kernel/Kconfig` 路径设计的，而 KSUN legacy 使用 `drivers/kernelsu/Kconfig`。

**解决过程**：
1. 创建 `susfs-kconfig-ksun.patch`，但 patch 格式与 GNU patch CLI 不兼容（patch 有 description text 开头导致无法 parse）
2. 改用 awk 提取 patch 中的 Kconfig 菜单，但 awk regex `^+menu` 中 `+` 被视为量词引发语法错误
3. 最终方案：在 workflow 中用 `printf` 逐行追加到 `drivers/kernelsu/Kconfig`

**教训**：不要依赖 patch 文件来修改不在 repo 管理范围内的文件；使用 shell 命令更可靠。

---

#### 问题 2：路径假设错误 —— `KernelSU/kernel/` 不存在

**现象**：`printf >> KernelSU/kernel/Kconfig` 报错 `Directory nonexistent`。

**产生原因**：我假设 KSUN legacy 安装到 `KernelSU/kernel/`（传统 KernelSU 的路径），但 `setup.sh` 克隆到 `KernelSU-Next/kernel/`，然后创建 `drivers/kernelsu → KernelSU-Next/kernel/` 符号链接。

**解决过程**：
1. 查看 `setup.sh` 源码，发现 `ln -sf KernelSU-Next/kernel drivers/kernelsu`
2. 将所有路径从 `KernelSU/kernel/` 改为 `drivers/kernelsu/`
3. 添加 fallback 路径以兼容两种布局

**教训**：**永远先验证文件实际位置再写代码**。一个简单的 `ls` 或 `curl` 可以避免很多问题。

---

#### 问题 3：dispatch 注入位置错误 —— prctl vs ioctl 架构差异

**现象**：`inject-susfs-dispatch.py` 在 `core/main.c` 中找不到 `ksu_handle_prctl` 函数 → `ERROR: no core/main.c found`。

**产生原因**：我一直假设 KSUN legacy 使用与旧版 KernelSU 相同的 prctl 通道架构。但 KSUN legacy 完全重写了通信机制——使用匿名 inode fd + ioctl 派发表（`supercall/dispatch.c`），没有 `ksu_handle_prctl`，没有 `core/main.c`。

**解决过程**：
1. 通过 GitHub API 查看实际目录结构，发现 `core/` 下只有 `init.c`
2. 查看 `supercall/dispatch.c` 源码，理解 ioctl 派发表机制
3. 完全重写 inject 脚本：移除 `patch_core_main()`，新增 `add_susfs_handlers_to_dispatch()`

**教训**：**在修改代码前先确认目标文件的真实结构**。不同 fork 的实现差异可能很大，不能靠"通常是这样"来推理。

---

#### 问题 4：sentinel regex 贪心匹配 → dispatch.c 编译错误

**现象**：`dispatch.c:938: error: designator in initializer for scalar type 'unsigned int'`

**产生原因**：sentinel 查找 regex `\.cmd\s*=\s*0\s*,[^;]*\.handler\s*=\s*NULL` 中 `[^;]*` 是贪婪匹配，消耗了过多文本（包括 `.handler = NULL`），导致 sentinel 实际未被匹配到。注入代码插入在意外位置，破坏了数组结构。

**解决过程**：
1. 将 regex 改为显式逐字段匹配，避免贪心问题
2. 另外发现 regex 只匹配 `.cmd = 0` 开始的行，但 sentinel entry 前面还有一个 `{` 行。注入在 `.cmd = 0` 之前导致 sentinel 的 `{` 悬空、字段失去 `{` 开头
3. 修复：用 `rfind('{', pos, s_match.start())` 回溯到 sentinel 的 opening brace

**教训**：**regex 的贪婪性是常见陷阱**，使用具体匹配替代 `.*` 或 `[^;]*` 更安全。同时要注意 regex 只匹配部分内容时的上下文完整性。

---

#### 问题 5：reboot.c hook 插入位置错误

**现象**：`reboot.c:599: error: expected identifier or '('`。hook 代码 `if (IS_ENABLED(CONFIG_KSU))` 被放在函数体外（文件作用域），产生语法错误。

**产生原因**：`apply-ksu-hooks.py` 中寻找 `__orderly_poweroff` 函数的 marker 机制复杂，涉及 `content.index(marker) + len(marker)` + 跳过变量声明行 + 计算偏移量。在某次构建中，marker 定位失败导致 hook 代码被追加到文件末尾。

**解决过程**：
1. 将 reboot.c 的 hook 改为简单字符串替换：`content.replace('\tret = run_cmd(poweroff_cmd);', hook, 1)`
2. 用直接替换代替复杂定位，简单可靠

**教训**：**复杂逻辑容易出错**。能用简单字符串替换解决的问题，不要用多层偏移量计算。

---

#### 问题 6：`susfs_init()` 插入位置错误（两个子问题）

**子问题 A —— 插入在 `#ifdef CONFIG_KSU_DEBUG` 内部**

**现象**：`susfs_init()` 在 `CONFIG_KSU_DEBUG=n` 时被预处理器移除，从未执行。

**产生原因**：`patch_core_init()` 的 banner 匹配模式在 `#ifdef CONFIG_KSU_DEBUG` 块内匹配到了 `pr_alert` 行，susfs_init() 被插入在该块内部。由于 `CONFIG_KSU_DEBUG=n`，整个块被预处理器跳过。

**子问题 B —— 插入在 `return 0;` 之后（死代码）**

**现象**：`susfs_init()` 被插入在函数闭合 `}` 之前，但在 `return 0;` 之后，成为永不执行的死代码。

**产生原因**：`lines.insert(close, ...)` 中 `close` 是函数闭合 `}` 的行号，插入在 `}` 之前但在 `return 0;` 之后。

**解决过程**：放弃 banner 匹配方法，改用 module_init 追踪函数体，找到函数内最后一个 `return` 语句在其前插入。

**教训**：**不要假设代码的上下文结构**。检查实际文件内容后再确定插入位置。`return 0;` 和 `}` 的位置关系需要精确。

---

#### 问题 7：module_init 匹配到错误的目标

**现象**：`ERROR: could not find insertion point for susfs_init()`。脚本找不到插入点。

**产生原因**：KSUN legacy 的 init.c 中有两个 `module_init`：`module_init(kernelsu_init_early)` 和 `module_init(kernelsu_init)`。脚本的 regex `module_init\s*\(\s*(\w+)\s*\)\s*;` 匹配到第一个（`kernelsu_init_early`），该函数没有 `return 0;`，导致找不到插入点。

**解决过程**：将 regex 改为显式匹配 `module_init\s*\(\s*kernelsu_init\s*\)\s*;`，跳过 early init。

**教训**：**使用通配符匹配模式时需要考虑多个匹配结果**。如果匹配可能命中多个目标，需要更精确的定位或加优先级逻辑。

---

#### 问题 8：`#include <linux/susfs.h>` 未找到

**现象**：`init.c:160: error: implicit declaration of function 'susfs_init'`。虽然在文件中用 grep 确认了 `#include <linux/susfs.h>` 存在，但编译器找不到声明。

**产生原因**：根因未完全确定，可能原因包括跨模块构建的 include 路径问题、头文件的条件编译导致声明不可见、或文件系统中的文件未同步到编译器看到的路径。

**解决过程**：
1. 放弃 `#include <linux/susfs.h>` 方案
2. 改用 `extern void susfs_init(void);` 直接声明
3. 在 workflow 中添加 grep 验证 + sed fallback 确保声明存在

**教训**：**`#include` 可能因为各种原因失败**（路径、权限、条件编译）。`extern` 直接声明更简单可靠，且不依赖头文件存在。

---

#### 问题 9：跨补丁符号缺失 —— 链接错误

**现象**：`ld.lld: error: undefined symbol: susfs_is_current_ksu_domain` 等 4 个符号未定义。

**产生原因**：`50_add_susfs_in_kernel-4.19.patch` 在 `fs/namespace.c` 中引用了 `susfs_is_current_ksu_domain`、`susfs_is_current_zygote_domain`、`ksu_try_umount`、`susfs_try_umount_all`，但这些函数只在 `10_enable_susfs_for_ksu.patch` 中定义。我们应用了 50_add 但未应用 10_enable。

**解决过程**：
1. 用 grep 确认所有被引用的跨补丁符号
2. 在 `susfs_stubs.c` 中添加对应的 stub 定义
3. 编译通过

**教训**：**补丁依赖分析是必要的前置步骤**。在决定不应用某个补丁前，需要用 grep 分析它被哪些其他补丁引用。

---

### 4.2 CI/CD 流程问题

#### 问题 10：YAML heredoc 缩进问题

**现象**：workflow 解析失败，错误信息 `This run likely failed because of a workflow file issue`。

**产生原因**：在 YAML `run: |` 块中使用 shell heredoc `<< 'EOF'`，heredoc 体缩进小于 YAML 首行缩进，导致 YAML 解释器提前截断。

**解决过程**：
1. 将 heredoc 替换为 `printf` 逐行追加
2. 避免 YAML 中任何多行字符串的缩进问题

**教训**：**YAML 的块缩进规则与 shell heredoc 的缩进规则不同**。在 YAML 中嵌入多行 shell 内容时，优先使用 `echo` / `printf` 而非 heredoc。

---

### 4.3 验证阶段问题

#### 问题 11：`su` 命令不可用

**现象**：未安装 KernelSU Manager APK 时，`adb shell su` 报 `su: inaccessible or not found`。

**原因**：KernelSU 不提供 `su` 二进制 —— root 功能通过内核模块 hook execve 实现，需要 KSU Manager APK 配合。

**解决**：使用 `adb root` 替代 `adb shell su` 获取 root shell。

---

## 5. 排查与修复中的错误复盘

### 5.1 错误模式总结

| 错误模式 | 出现次数 | 典型表现 | 根本原因 |
|----------|----------|----------|----------|
| **路径假设** | 3 次 | `File not found`、`Directory nonexistent` | 未验证实际文件位置，凭经验猜测 |
| **架构假设** | 2 次 | API/函数不存在、行为不符预期 | 未验证目标组件的实际接口设计 |
| **regex 问题** | 2 次 | 贪心匹配、语法错误 | regex 设计与实际数据不匹配 |
| **插入位置** | 3 次 | 死代码、错误条件块内、函数体外 | 未验证上下文的精确结构 |
| **字符串替换** | 1 次 | 缩进不匹配、无法匹配 | 未确认实际文件中的空白字符 |

### 5.2 需要纠正的思维方式

#### 🔴 核心问题：不验证假设就写代码

这是贯穿整个 Phase 1a 最常见的错误。每次构建失败后分析根因，90% 的情况是"我以为 X 是 Y，但实际不是"。

**改正方法**：
```
改前：
  "KSUN legacy 应该用 prctl 通道"
  → 写代码
  → 构建失败
  → 才发现用的是 ioctl

改后：
  "KSUN legacy 的通信机制是什么样的？"
  → 下载实际源码查看
  → 确认是 ioctl 派发表
  → 写代码
  → 一次通过
```

**具体行动规则**：
1. 修改任何文件前，先用 `curl` 或 `cat` 查看目标文件的**实际内容**
2. 确认路径、函数名、签名、缩进方式后再写注入代码
3. 不确定时先验证，不确定不写代码

#### 🟡 问题：复杂逻辑代替简单方案

多次使用多层偏移量计算、正则匹配、循环跳转等复杂逻辑来定位插入点，而这些都可以用简单的字符串替换解决。

**改正方法**：优先选择最直接的方法。如果字符串替换能解决问题（如 `content.replace()`），就不需要用 regex + 偏移量计算。

#### 🟡 问题：一次性修复多问题

一次 commit 修复多个不相关的 bug，导致：
1. 难以追溯每个问题的具体修复
2. 部分修复依赖后续修复才能生效
3. 构建失败时难以定位是哪个修复导致的

**改正方法**：每个问题一个 commit，每个 commit 只解决一个问题。

### 5.3 流程改进建议

```
当前流程：
  写代码 → 提交 → 等 15min 构建 → 失败 → 查日志 → 再修

建议流程：
  1. 下载实际目标文件（curl / cat）
  2. 验证所有假设（路径/函数名/格式）
  3. 在本地模拟修改逻辑（Python / sed）
  4. 确认无误后提交
  5. 等待构建验证
```

---

## 6. 参考资料与技术借鉴

### 6.1 直接参考的项目

| 项目 | 用途 | URL |
|------|------|-----|
| rifsxd/KernelSU-Next (legacy) | KernelSU 实现，ioctl 派发表架构 | https://github.com/rifsxd/KernelSU-Next |
| simonpunk/susfs4ksu (kernel-4.19) | SUSFS v1.5.5 官方源码 | https://gitlab.com/simonpunk/susfs4ksu |
| LineageOS/android_kernel_oneplus_sm8250 | OnePlus 8T 内核源码 | https://github.com/LineageOS/android_kernel_oneplus_sm8250 |
| tiann/KernelSU | 传统 KernelSU（参考 prctl 架构） | https://github.com/tiann/KernelSU |

### 6.2 调研参考的资料

| 资料 | 提供者 | 内容 | 评估 |
|------|--------|------|------|
| SUSFS v2.2.0 移植指南 | DeepSeek | 系统性 porting 指南，checklist | 概念框架好，但将 v1.5.5 称为 v2.2.0 有混淆 |
| SUSFS 4.14→4.19 移植指南 | GLM 5.2 Max | 钩子点矩阵、逐组件适配代码 | **最准确**，正确区分基线 v1.5.x + 前向移植 v2.x |
| SUSFS 4.19 适配方案 + 脚本 | Grok | 完整自动化脚本、5 个特制 patch、GHA workflow | **工具完整性最好**，但 patch 数量不全 |
| SUSFS kebab 4.19 port | Arena Agent | cherry-pick commit 列表、冲突适配表 | **最接地气**，直接面对实际冲突 |

### 6.3 技术借鉴

| 借鉴内容 | 来源 | 应用到何处 |
|----------|------|------------|
| KSUN legacy 的 ioctl 派发表架构 | rifsxd/KernelSU-Next | inject 脚本重写方向 |
| v1.5.5 基线 + 前向移植 v2.x 的策略 | GLM 报告 | Phase 1a/1b 的路线设计 |
| 钩子点兼容性矩阵 | GLM 报告 | 理解哪些 hook 需适配 |
| sentinel 格式确认 | dispatch.c 源码 | 正则匹配设计 |
| 50_add patch 引用的外部符号 | grep 分析 | stub 补全 |

---

## 7. 经验与收获

### 7.1 技术收获

#### 内核模块构建
- **Kconfig 系统**：`merge_config.sh` 静默丢弃未注册的符号，需要确保 Kconfig 菜单先被注入
- **内核模块的 include 路径**：-I$(srctree)/include 是默认路径，symlink 不影响 include 解析
- **链接顺序**：obj-y 和 obj-$(CONFIG_*) 的链接顺序由 Makefile 决定，跨模块符号引用在内核 built-in 方式下自动解析

#### KernelSU 架构
- **传统 vs KSUN legacy 的架构差异**：prctl 通道 vs ioctl 派发表，这是最关键的认知转变
- **KSU 手动 hook 机制**：在 VFS 文件中插入 `ksu_handle_*` 调用，通过 extern 声明匹配 KSU 模块定义
- **sys_reboot 通道**：KSUN legacy 也保留 `ksu_handle_sys_reboot` 作为备用通信通道

#### SUSFS 机制
- **工作流程**：用户态下发命令 → KSU ioctl dispatch → `fs/susfs.c` 维护状态 → VFS hook 点执行隐藏/伪造
- **依赖关系**：50_add patch 引用的部分函数（如 `susfs_is_current_ksu_domain`）定义在 10_enable patch 中
- **版本差异**：v1.5.5（kernel-4.19 分支）与 v2.x（主分支）的函数签名和特性集有显著差异

#### C 编译问题
- **C89 与 C99 的差异**：内核 4.19 默认使用 `-std=gnu89`，不支持 mixed declarations and code
- **`__user` 属性**：仅影响 sparse 检查，不影响 GCC/Clang 编译
- **`IS_ENABLED()` 宏**：在条件编译和运行时条件中均可使用

### 7.2 流程收获

1. **验证 > 假设**：每次修改前确认实际文件内容，比事后调试节省 10 倍时间
2. **最小化修改**：能用简单字符串替换解决的问题，不要用复杂逻辑
3. **渐进验证**：每个修改都通过构建验证，不要累积多个未验证的修改
4. **保留所有探索记录**：四份 AI 调研资料各有侧重，综合后得到最完整的方案

### 7.3 值得深入学习的方向

| 方向 | 原因 | 学习资源 |
|------|------|----------|
| Linux VFS 层 | SUSFS 的核心工作域（dentry、inode、mount） | kernel.org/doc/Documentation/filesystems/ |
| Kconfig / Kbuild 系统 | 理解内核模块注册和配置 | Linux Kernel Makefiles 文档 |
| ARM64 内核启动流程 | 理解 initcall、模块加载时机 | kernel.org/doc/Documentation/arm64/ |
| SELinux 安全机制 | is_ksu_domain、sid 等概念 | SELinux Notebook |
| LLVM/clang LTO | 可能消除手动 hook 函数 | Clang documentation |
| 内核符号隐藏 | kallsyms 过滤机制 | kernel/kallsyms.c |

---

## 8. 后续计划

### 8.1 路线图

```
Phase 1a (当前) ──▶ Phase 1b ──▶ Phase 2 ──▶ Phase 3
    已完成         进行中         规划中      未来
```

### 8.2 Phase 1b：SUSFS v2.x 功能前向移植

**目标**：在 v1.5.5 内核上叠加 sidex15 4.14 backport 中独有的 v2.x 特性。

**计划特性**：

| 特性 | 来源 | 说明 |
|------|------|------|
| sus_map | sidex15 v2.2.0 | 隐藏 `/proc/pid/maps` 中的条目 |
| AVC log spoofing | sidex15 v2.2.0 | 伪造 SELinux avc 日志 |
| sus_kstat 哈希表化 | sidex15 v2.2.0 | 提高 stat 伪造性能 |
| bootconfig spoof | sidex15 v2.2.0 | 伪造 `/proc/bootconfig` |
| open_redirect 增强 | sidex15 v2.2.0 | 改进文件打开重定向 |

**实施策略**：
1. 以官方 kernel-4.19 分支（v1.5.x）为基线
2. 从 sidex15 的 fs/susfs.c 中提取 v2.x 新增函数
3. 逐个移植到当前内核
4. 每次一个特性，构建验证后再进行下一个

### 8.3 Phase 2：10_enable 补丁适配

**目标**：将 `10_enable_susfs_for_ksu.patch` 适配到 KSUN legacy 的 `drivers/kernelsu/` 结构。

**工作内容**：
1. 将 dispatch 逻辑从我们的自定义 handler 迁移到 10_enable 补丁的正式 dispatch
2. 添加 `susfs_on_post_fs_data()`、`susfs_try_umount_all()` 等自动功能
3. 移除对应的 susfs_stubs.c 中的 stub（由正式实现替代）

### 8.4 Phase 3：用户态工具集成

**目标**：编译配套的 ksu_susfs 用户态工具，并测试完整功能。

**工作内容**：
1. 适配 ksu_susfs 工具使用 ioctl 通道（而非 prctl）
2. 安装 KSU Manager APK 验证 root
3. 验证 SUSFS 隐藏功能（银行 App、Momo 等检测工具）

---

## 9. 文件清单与作用

### 工作流与 CI

| 文件 | 作用 |
|------|------|
| `.github/workflows/build-ksu-debug.yml` | GHA CI 主流程：克隆、打补丁、配置、编译、验证、打包 |

### 脚本

| 文件 | 作用 |
|------|------|
| `scripts/apply-ksu-hooks.py` | 在 fs/open.c、fs/exec.c、fs/read_write.c、kernel/reboot.c 中注入 KSU manual hook 调用 + extern 声明 |
| `scripts/inject-susfs-dispatch.py` | 在 KSUN legacy 中注入 SUSFS ioctl dispatch handler + `susfs_init()` 调用 |
| `build-boot-img.py` | 打包 boot.img，支持 `--append-cmdline` |

### 内核补丁与配置

| 文件 | 作用 |
|------|------|
| `kernel-patches/ksu.config` | KSU + SUSFS Kconfig 配置片段（用于 merge_config.sh） |
| `kernel-patches/debug.config` | 调试配置：pstore/ramoops、initcall_debug、详细日志 |
| `kernel-patches/susfs_stubs.c` | SUSFS v2.x 函数的兼容 stub，满足 50_add patch 的链接依赖 |
| `kernel-patches/fix_strnstr_msm_drv.patch` | 修复 strnstr() 三参数签名 |
| `kernel-patches/fix_dtb_no_qcom.patch` | 禁用 qcom 参考平台 DTS 编译 |

### 产物

| 文件 | 说明 | 用途 |
|------|------|------|
| `Image` | 未压缩内核 | 直接替换 boot.img 中的内核 |
| `Image.gz` | gzip 压缩内核 | 部分打包工具需要 |
| `ksu-debug-boot.img` | 带 KSU+SUSFS+调试的 boot.img | `fastboot boot` 临时启动或 `fastboot flash boot` 刷写 |
| `config.txt` | 内核编译配置 | 验证配置选项是否正确 |

---

## 附录：GHA 构建迭代记录

| Build ID | Commit | 结果 | 失败原因 |
|----------|--------|------|----------|
| 28429841040 | Phase 1a 初始 | ✅ 成功 | - |
| 28431381042 | SUSFS Kconfig 注册 | ❌ | `KernelSU/kernel/Kconfig` 路径不存在 |
| 28431536188 | inject 脚本重写 | ❌ | Kconfig patch 格式 + awk 正则错误 |
| 28432125544 | YAML herdock 修复 | ❌ | YAML heredoc 缩进 |
| 28432368904 | printf 追加 Kconfig | ❌ | 同上（更早的提交） |
| 28432669144 | 审计发现 3 Bug | ❌ | `KernelSU/kernel/Kconfig: Directory nonexistent` |
| 28433072765 | 路径改为 drivers/kernelsu | ❌ | `ERROR: no core/main.c found` |
| 28434104031 | ioctl 重写 dispatch | ❌ | `reboot.c:599` + `dispatch.c:938` |
| 28434380862 | 调整 ioctl cmd 0x55 | ❌ | 同上 |
| 28435224249 | 移除 uapi 依赖 | ❌ | dispatch.c:938 sentinel regex 贪心 |
| 28435775937 | reboot.c 简化 | ❌ | dispatch.c:938（同上） |
| 28436239156 | dispatch.c regex 修正 | - | （后续提交覆盖） |
| 28436683814 | init.c 两大 Bug | ❌ | module_init 匹配到错误目标 |
| 28437155503 | module_init 显式匹配 | ❌ | susfs.h header 未找到 |
| 28437757640 | extern 替代 include | ❌ | 链接错误：4 个 stub 缺失 |
| (最新) | 添加 stub | ✅ ✅ | **首次完全通过** |

---

*本文档覆盖了 Phase 1a 的全部工作内容。后续阶段将在此基础上迭代。*
