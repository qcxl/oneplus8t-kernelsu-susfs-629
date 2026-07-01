---
name: kport
description: 内核功能移植全程引导——源码阅读、全链路审计、提交检查、修复复盘、刷机验证。自动加载项目上下文。
metadata:
  project: kernel-porting
---

# /kport — 内核功能移植审查

## 阶段 1：移植前检查

### 1a. 源码阅读
阅读顺序：头文件 → 结构体 → 声明 → 实现 → 补丁。

- 读取 `susfs_def.h`，记录所有 CMD / INODE_STATE / AS_FLAGS 等常量
- 读取 `susfs.h`，基线 vs 目标逐字段对比结构体
- 逐函数对比签名变化（int func(xxx*) → void func(void**)）
- 读取函数实现，标注所有外部依赖
- 读取 50_add 补丁，定位 VFS 挂钩位置

### 1b. 依赖追踪
- 全局变量：覆盖搜索 KSUN 全部源码确认存在
- 锁机制：spin_lock/mutex/SRCU/RCU 在 kernel 4.19 可用性
- 外部函数：kern_path/kzalloc/override_creds 等逐一确认

### 1c. 全链路追踪
- 代码路径：用户态命令 → syscall → dispatch → 功能函数 → VFS
- 确认注入标记在目标文件中存在
- 注入脚本检查插入成功，失败返回 False
- dispatch 引用的每个 CMD_* 常量在 susfs_def.h 中有定义

### 1d. 边界验证
- 符号冲突 / 内核版本兼容 / 幂等性 / Kconfig 完备
- 局部结构体自包含（不引用外部类型）
- 缩进一致（Python 4空格，C 代码 \t）

### 1e. 常见失败模式对照
静默跳过 / 文件版本差异 / 前向声明 / 替换丢失 #define / 双 #define / CI 步骤顺序

---

## 阶段 2：代码审计 + 提交

- python3 py_compile 检查每个修改的 inject 脚本
- grep /Users/ /home/ 确认无硬编码路径
- dispatch 条目（IOCTL + reboot 两处）都添加了
- ksu.config 和 GHA workflow Kconfig 同步
- 运行 bash scripts/pre-flight-check.sh，0 阻断才能提交

---

## 阶段 3：修复后复盘

每次修复后在 ERRORS.md 新增条目：现象 / 根因 / 教训 / 锚点。
可自动化的更新 pre-flight-check.sh。
commit message 引用对应 E00N 编号。

---

## 阶段 4：刷机验证

按 FLASH_PROCEDURE.md：
1. 环境检查（adb/fastboot/root）
2. 刷机包完整性（ANDROID! 魔数）
3. 基线保存 + dmesg/logcat 监控
4. fastboot boot
5. 验证：panic 检查 / PMIC 原因 / ksud 命令 / kallsyms 符号

---

## 原则

一次只移植一个函数。不武断删除功能，做完整可行性调研。
所有 bug 必须有根因分析才提交。提交前 pre-flight-check 0 阻断。
