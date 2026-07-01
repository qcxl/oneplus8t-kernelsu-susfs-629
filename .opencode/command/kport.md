---
description: Kernel porting review — src-read / deps / trace / verify / audit / fix / flash
---

加载 kport skill，根据 $ARGUMENTS 子命令执行对应阶段：

| 子命令 | 阶段 | 功能 |
|--------|------|------|
| `/kport` | - | 显示此帮助 |
| `/kport read` | 1a | Source code reading — headers, structs, signatures, deps |
| `/kport deps` | 1b | Dependency tracking — globals, locks, external funcs |
| `/kport trace` | 1c | Full-chain trace — user→syscall→dispatch→VFS |
| `/kport verify` | 1d | Boundary check — symbol conflicts, Kconfig, idempotency |
| `/kport audit` | 2 | Code audit — py_compile, hardcoded paths, dispatch, pre-flight |
| `/kport fix` | 3 | Post-mortem — ERRORS.md, pre-flight update, E00N commit |
| `/kport flash` | 4 | Flash verify — env, boot.img integrity, fastboot, ksud |
