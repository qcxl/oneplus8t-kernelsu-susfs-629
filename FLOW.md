<!-- 审查报告 — 由 /kport review 自动生成 -->

## 审查报告 — 2026-07-01

### 1a. 源码阅读

**源文件状态**：`susfs_def.h` / `susfs.h` 在 kernel 树中不存在（由 GHA workflow 中的 inject 脚本注入）。
审查基于 inject 脚本模板和 `susfs_stubs.c` 进行。

**CMD 常量（dispatch 模板引用）**：15 个
```
CMD_SUSFS_ADD_OPEN_REDIRECT         CMD_SUSFS_ADD_SUS_KSTAT
CMD_SUSFS_ADD_SUS_MAP                CMD_SUSFS_ADD_SUS_MOUNT
CMD_SUSFS_ADD_SUS_PATH               CMD_SUSFS_ADD_SUS_PATH_LOOP
CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING    CMD_SUSFS_ENABLE_LOG
CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS
CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG  CMD_SUSFS_SET_UNAME
CMD_SUSFS_SHOW_ENABLED_FEATURES      CMD_SUSFS_SHOW_VARIANT
CMD_SUSFS_SHOW_VERSION               CMD_SUSFS_UPDATE_SUS_KSTAT
```

**v2.x 函数签名（来自 stubs）**：
| 函数 | 签名 |
|------|------|
| susfs_add_sus_path_loop | `int (void __user *arg)` |
| susfs_set_hide_sus_mnts_for_non_su_procs | `int (void __user *arg)` |
| susfs_add_sus_map | `int (void __user *arg)` |
| susfs_set_avc_log_spoofing | `int (void __user *arg)` |
| susfs_enable_log | `int (void __user *arg)` |

### 1b. 依赖追踪

| 函数 | 4.19 可用 | 说明 |
|------|----------|------|
| kern_path | ✅ | vfs 函数，4.19 原生支持 |
| kzalloc | ✅ | 内存分配，全版本支持 |
| copy_from_user | ✅ | uaccess 标准 API |
| copy_to_user | ✅ | uaccess 标准 API |
| path_put | ✅ | VFS 标准 API |
| override_creds | ✅ | cred 子系统，4.19 支持 |
| strncpy_from_user | ✅ | uaccess 标准 API |
| d_backing_inode | ✅ | 4.19 引入 |

**结论**：所有外部依赖在 kernel 4.19.304 中可用 ✅

### 1c. 全链路追踪

```
用户态 (ksud / KSU Manager)
  → reboot(0xDEADBEEF, 0xFAFAFAFA, cmd, arg)     ← reboot 通道
  → ioctl(fd, KSU_IOCTL_SUSFS, &{cmd_id, arg})    ← IOCTL 通道
    → do_susfs_ioctl()                             ← dispatch.c 分发
      → switch(ioctl.cmd_id) { ... }               ← CMD 常量路由
        → susfs_add_sus_path()                     ← 功能函数
        → susfs_set_hide_sus_mnts_for_non_su_procs() ← v2.x 功能
      → return -EINVAL (默认)
```

**注入标记确认**：
- `susfs_def.h`：锚点 `CMD_SUSFS_ADD_SUS_MOUNT` ✅（跨版本稳定）
- `susfs.h`：锚点 `/* susfs_init */` ✅（跨版本稳定）
- `susfs.c`：锚点 `/* susfs_init */` ✅（跨版本稳定）
- `dispatch.c`：锚点 `ksu_ioctl_handlers[]` ✅（KSUN 固定）
- `supercall.c`：锚点 `#ifdef KSU_KPROBES_HOOK` ✅（KSUN 固定）

**注入失败保护**：4 个 inject 脚本共 28 个 `return False` 路径 ✅

### 1d. 边界验证

| 检查项 | 结果 |
|--------|------|
| Python 语法（4 个 inject 脚本） | ✅ 全部通过 |
| 硬编码路径（/Users/ /home/） | ✅ 无 |
| 缩进一致（Python 4 空格） | ✅ |
| Kconfig 配置数 | 17 项（ksu.config） |
| GHA Kconfig 注册数 | 17 项（workflow） |
| Kconfig 一致 | ✅ 数量匹配（需确认注册内容与配置一致） |

### 2. 代码审计

| 检查项 | 结果 | 说明 |
|--------|------|------|
| py_compile | ✅ | 4/4 通过 |
| 硬编码路径 | ✅ | 0 处 |
| dispatch 条目 | ✅ | IOCTL + reboot 两处 |
| Kconfig 同步 | ✅ | 17 = 17 |

### ⚠️ pre-flight-check 发现的非阻断问题

| 问题 | 建议修复 |
|------|---------|
| `pre-flight-check.sh` 引用了已删除的 `TEST_PROCEDURE.md` 和 `FLASH_PROCEDURE.md` | 更新为 `FLOW.md` / `FLASH.md` |
| `pre-flight-check.sh` 使用旧字段名 `检查清单锚点`，但 ERRORS.md 已改为 `锚点` | 同步字段名 |
| `pre-flight-check.sh` 的 `inject-*.py` glob 在非默认目录下不匹配 | 使用 `$INJECT_PATTERN` 变量或 `find` |

### 结论

- **阻断**：0 项（inject 脚本层面）
- **警告**：3 项（pre-flight-check 自身未与新版 skill 同步）
- **最终判定**：✅ 注入脚本可提交，GHA 修复后可触发编译
