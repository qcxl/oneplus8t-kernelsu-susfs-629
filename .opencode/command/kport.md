---
description: 内核功能移植审查流程——源码阅读、全链路审计、提交检查、修复复盘、刷机验证
---

加载 kport skill，按阶段引导 $ARGUMENTS

可用阶段：
- **阶段 1**：移植前检查（源码阅读 → 依赖追踪 → 全链路追踪 → 边界验证 → 失败模式对照）
- **阶段 2**：代码审计 + 提交（py_compile → 路径检查 → dispatch → Kconfig → pre-flight-check）
- **阶段 3**：修复后复盘（ERRORS.md 记录 → pre-flight-check 更新 → commit 引用 E00N）
- **阶段 4**：刷机验证（环境检查 → 包完整性 → fastboot boot → ksud/kallsyms 验证）
