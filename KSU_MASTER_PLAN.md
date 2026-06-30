# OnePlus 8T KernelSU + SUSFS 完整方案文档

## 一、项目目标

为 **OnePlus 8T (kebab)** / **LineageOS 20** (Android 13) / **内核 4.19.304** 编译带 **KernelSU + SUSFS** 的可启动内核。

**GitHub 仓库：** https://github.com/qcxl/oneplus8t-kernelsu-susfs-629
**内核源：** LineageOS/android_kernel_oneplus_sm8250 @ `5dea892fe7e4`
**设备：** Snapdragon 865 (sm8250/kona), Non-GKI

---

## 二、已完成进度

| 阶段 | 状态 | 详情 |
|------|------|------|
| 构建环境 | ✅ | GHA CI, ubuntu:20.04, clang-r450784d, LLVM=1 |
| Vanilla 内核启动 | ✅ | 无 KSU 内核可正常 fastboot boot |
| boot.img 打包 | ✅ | 修复 cmdline 空 + ramdisk 偏移 bug |
| 调试能力 | ✅ | debug.config (ramoops + initcall_debug) |
| Step 0 准备 | ✅ | 配置文件已剥离 SUSFS，准备验证纯 KSU |

---

## 三、实验回顾与结论

### 3.1 尝试过的所有 KernelSU Fork

| Fork / 分支 | 结果 | 原因 |
|------------|------|------|
| **SukiSU-Ultra `main`** | ❌ 启动崩溃 | 使用 kprobe hook，而 SukiSU 文档自己说 non-GKI "Not applicable" |
| **SukiSU-Ultra `dev/builtin`** | ❌ 编译失败 | dispatch.c/supercalls.c 需要 SUSFS **v2.0+** 符号，kernel-4.19 最高 v1.4.2 |
| **rsuntk `susfs-rksu-master`** | ❌ 编译失败 | 同上，也需要 SUSFS v2.0+ 符号 |
| **tiann/KernelSU `main`** | ❌ **注定失败** | Kconfig: `depends on KPROBES && EXT4_FS`，硬依赖 kprobe，4.19 一定崩溃 |
| **KernelSU-Next `legacy`（当前）** | 🟡 构建中 | **首次正确支持 manual hook**：Kconfig 有 `KSU_MANUAL_HOOK default y if !KPROBES` |

### 3.2 关键发现（来自 LLM 交叉验证）

| 发现 | 证据 | 影响 |
|------|------|------|
| tiann/KernelSU main 的 `depends on KPROBES` | Kconfig 第5行 | **当前构建停止**，此路不通 |
| KSUN legacy 的 `MANUAL_HOOK default y if !KPROBES` | Kconfig 第 44-47 行 | **这是我们要的正确方案** |
| KPROBES_HOOK 说明 "not be used below 5.10" | Kconfig help 文本 | 印证 non-GKI 4.19 必须禁用 kprobe |
| SUSFS kernel-4.19 最高 v1.4.2 | GitLab tags 验证 | 没有官方的 v2.0+，社区有 backport |
| larrypaul93 仓库已验证 OnePlus 8T | README + 大量 workflow | **最可信的参考** |

---

## 四、当前方案：KernelSU-Next legacy

### 4.1 为什么选它

| 维度 | KernelSU-Next legacy | 其他 fork |
|------|-------------------|-----------|
| **KPROBES 依赖** | **否**（MANUAL_HOOK default y if !KPROBES） | tiann/rsuntk main 都硬依赖 |
| **Manual Hook** | ✅ 原生支持（Kconfig 选项完整） | tiann 没有此选项 |
| **SUSFS 兼容** | ⚠️ 需外部 v1.4.2/v1.5.5 补丁 | 所有 fork 都一样 |
| **验证状态** | larrypaul93 已验证 OnePlus 8T | — |
| **4.19 non-GKI 支持声明** | Kconfig 明确标注 <5.10 禁止 kprobe | 唯一明确声明的 fork |

### 4.2 当前 ksu.config 配置

```
CONFIG_KSU=y
CONFIG_KSU_MANUAL_HOOK=y
# CONFIG_KSU_KPROBES_HOOK is not set
# CONFIG_KSU_SUSFS is not set    ← Step 0，先不叠 SUSFS
CONFIG_KALLSYMS=y
CONFIG_KALLSYMS_ALL=y
```

### 4.3 当前 GHA workflow 的兼容性修复

| 修复 | 目标文件 | 原因 |
|------|---------|------|
| linux/pgtable.h 注释 | sucompat.c | 4.19 无此头文件 |
| linux/safe_mode.h 注释 | main.c | 同上 |
| strncpy_from_user_nofault→strncpy_from_user | event.c, ksud_integration.c | 4.19 无 nofault 变体 |
| ksu_strncpy_from_user→strncpy_from_user | event.c | 同上 |
| copy_to_kernel_nofault→memcpy | patch_memory.c | 同上 |
| MODULE_IMPORT_NS 注释 | init.c | 同上 |
| file_wrapper __init/__exit 移除 | file_wrapper.c | builtin 分支 signature 不匹配 |

---

## 五、后续详细计划

### Phase 0：验证纯 KSU 启动（当前步骤）

| 步骤 | 操作 | 预计时间 |
|------|------|---------|
| 0.1 | 等待 GHA 构建完成（KSUN legacy + 纯 KSU） | ~15 min |
| 0.2 | `fastboot boot debug-boot.img` 测试 | ~5 min |
| 0.3 | 如果成功 → 安装 KSU Manager 验证 root | ~5 min |
| 0.4 | 如果崩溃 → 检查 kprobe 残留 + hook 点位置 | 额外迭代 |

**如何判断是否是 hook 点位置问题：**
- 如果纯 KSU 崩溃且无日志，先在 `fs/exec.c` 的 execveat hook 位置加 `pr_err()` 测试
- 每次只启用 1 个 hook 点，二分定位

### Phase 1：叠 SUSFS（纯 KSU 验证通过后）

| 步骤 | 操作 |
|------|------|
| 1.1 | 在 ksu.config 取消 `# CONFIG_KSU_SUSFS is not set`，添加 SUSFS 配置项 |
| 1.2 | 在 workflow 中添加 SUSFS 克隆和补丁步骤 |
| 1.3 | 克隆 simonpunk/susfs4ksu `kernel-4.19` 分支（tag v1.4.2-kernel-4.19） |
| 1.4 | 应用 `50_add_susfs_in_kernel-4.19.patch` |
| 1.5 | 复制 `fs/susfs.c`, `include/linux/susfs.h` 等到内核树 |
| 1.6 | 编译 + 测试 |

### Phase 2：优化与验证

| 步骤 | 操作 |
|------|------|
| 2.1 | 安装 KSU Manager + SUSFS 模块 |
| 2.2 | 验证 root 权限 |
| 2.3 | 验证 SUSFS 隐藏功能 |
| 2.4 | 测试稳定性（反复重启） |
| 2.5 | 刷入 boot_a 永久使用 |

### Phase 3：如果需要 SUSFS v2.0+ 功能

向上游 reference sidex15 的 SUSFS 2.0 backport 到 4.14（`https://github.com/sidex15/android_kernel_lge_sm8150`），
移植到 4.19 的工作量约 1-2 周，仅在有强需求时做。

---

## 六、重要注意事项

### 6.1 必须避免的坑

| 坑 | 说明 |
|----|------|
| **不要用 tiann/KernelSU main** | 硬依赖 kprobe，non-GKI 4.19 一定崩溃 |
| **不要用 SukiSU main** | 一样用 kprobe |
| **不要用 rsuntk susfs-rksu-master** | 需要 SUSFS v2.0+，4.19 没有 |
| **不要忽视 KPROBES** | 手动 hook 模式下必须 `CONFIG_KPROBES=n` |
| **不要在 Step 0 前叠 SUSFS** | 两个问题混在一起无法排查 |

### 6.2 如果纯 KSU 仍然崩溃

1. **先验证 hook 点位置**：`fs/exec.c` 的 execveat 是最关键的
2. **检查 kprobe 残留**：确保 `CONFIG_KPROBES=n`
3. **加 earlycon 到 cmdline**：`earlycon=msm_geni_serial,0x988000`
4. **二分定位**：每次只启用一个 hook 点

### 6.3 参考资源

| 资源 | 链接 | 说明 |
|------|------|------|
| larrypaul93's build | https://github.com/larrypaul93/oneplus8-kernelsu-susfs | OnePlus 8T 已验证 |
| JackA1ltman patches | https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd | SUSFS 2.0 社区 backport |
| sidex15 backport | https://github.com/sidex15/android_kernel_lge_sm8150 | v2.2.0 backport to 4.14 |
| SUSFS GitLab | https://gitlab.com/simonpunk/susfs4ksu | 官方 SUSFS |
| KernelSU Next | https://github.com/rifsxd/KernelSU-Next | 当前使用的 fork |

### 6.4 ramoops 日志问题

sm8250 的 XBL/ABL 在每次复位时重新初始化 DDR，清空 ramoops 保留内存（0xb0000000）。
**不依赖 ramoops，改用：**
1. Step 0 先纯 KSU 再叠 SUSFS（解耦两个问题）
2. 二分定位（每次只开一个 hook 点）
3. earlycon（如果崩溃点够晚）
4. UART 线（终极方案，需要焊测试点）

---

## 七、决策树

```
当前：KSUN legacy 构建中
│
├─ ✅ 编译通过
│  ├─ 🟢 fastboot boot 启动成功
│  │    ├─ 验证 root ✓
│  │    ├─ 进入 Phase 1（叠 SUSFS）
│  │    └─ 最终：功能完整的 KSU+SUSFS 内核
│  │
│  └─ 🔴 fastboot boot 崩溃
│       ├─ 检查 CONFIG_KPROBES=n
│       ├─ 检查 hook 点位置
│       └─ 每次只开 1 个 hook 点二分定位
│
└─ ❌ 编译失败
   ├─ 检查错误类型
   └─ 可能需要调整 ksu.config 或兼容修复
```

*文档版本: v1.0 | 2026-06-30 | 对应 commit: a167dfa*
