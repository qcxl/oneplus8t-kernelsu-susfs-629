# 错误经验库

> 本文件由 TEST_PROCEDURE.md 拆分而来，每次修复后在此新增条目。
> 主流程文档见 [TEST_PROCEDURE.md](TEST_PROCEDURE.md)。

## 🧠 错误经验库（每次修复后更新）

### E001：`#define` 字符串替换缺少前缀（Batch 1）
**现象**：编译报 `macro name must be an identifier`，生成 `#define #define CMD_...`
**根因**：替换目标字符串 `'CMD_SUSFS_ADD_SUS_MAP'` 不包含前面的 `#define`，替换后变 `#define #define ...`
**教训**：替换预处理指令时必须包含完整的 `#define NAME VALUE` 行，切勿只匹配 NAME
**检查清单锚点**：见「替换丢失 `#define`」项 ✅

### E002：注入锚点在目标文件中不存在，静默跳过（Batch 1）
**现象**：编译报 `incomplete type / forward declaration`。struct 定义不存在，但函数声明已插入
**根因**：`inject_susfs_h()` 使用 `int susfs_get_enabled_features` 做锚点，但 GHA 实际文件中函数签名不同（本地读的是 hypermezo4 v1.5.9 镜像，GHA 用 gitlab 原始版）。插入静默失败，return True
**教训**：
1. 注入脚本必须检查插入是否成功，失败返回 False
2. 本地文件 ≠ GHA 源文件。差异源：gitlab 原始版 vs GitHub 镜像版 vs 50_add 补丁生成版
3. 使用 `/* susfs_init */` 等稳定标记做锚点（跨版本不变）
**检查清单锚点**：见「确认注入标记」和「注入脚本必须检查」项 ✅

### E003：多步插入产生半状态（Batch 1）
**现象**：先 `lines.insert(func)` 再 `content.replace(func, func + wrapper)`，后一步失败则只有 func 被插入
**根因**：分两步插入相关代码，没有原子性保证
**教训**：所有逻辑上必须同时存在的代码（如 struct + 声明、avc_func + enable_log_wrapper）必须合并为一次字符串后用单次插入
**检查清单锚点**：见「缩进一致性」项 ✅

### E004：`#ifdef` 子选项未在 Kconfig 注册（Batch 1 预防）
**潜在风险**：新增 `#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING` 保护的代码，如果 Kconfig 未注册且 ksu.config 未设置，代码被编译但选项不生效
**预防**：每次新增 `#ifdef CONFIG_*` 时，同步检查 `ksu.config` 和 GHA workflow 的 Kconfig 注册

### E005：本地文件与 GHA 实际源文件不一致
**风险**：gitlab 原始版 vs GitHub 镜像版 vs 50_add 补丁生成的版本之间可能有差异。本地的 `/tmp/susfs-v1.5/` 来自 hypermezo4 镜像（v1.5.9），GHA 从 gitlab 克隆（未知精确版本）
**预防**：锚点/标记优先使用不易随版本变更的固定字符串（如 `/* susfs_init */`），而非特定代码行（如 `int susfs_get_enabled_features`）

### E006：武断删除功能，未做可行性调研
**现象**：发现 `ksu_cred` 在预读的 KSUN 源码中未搜到，直接判定"无法移植"要删掉 `sus_path_loop`
**根因**：搜索范围不够全——`ksu_cred` 实际存在于 `kernel/include/ksu.h`，只是不在最初搜索的 `kernel/ksu.c` 中
**教训**：
1. **任何功能不得在未完成完整可行性调研前标记为"无法移植"**
2. 搜索依赖时覆盖所有可能的文件路径，不仅仅是自己认为"可能"的位置
3. 对缺失的依赖，先查 3 种可能：① 改名了在不同位置 ② 在内核头文件中 ③ 需要自己实现 shim/wrapper
4. 确认不可行后才记录原因、提交决策说明，**不可静默删除**
**检查清单锚点**：见「功能可行性调研」项 ✅

### E007：脚本中使用硬编码本地绝对路径（Batch 2）
**现象**：GHA 构建报 `FileNotFoundError: /Users/weifeng/...`，连续 3 次构建失败
**根因**：`patch_dispatch_template()` 中写了硬编码路径 `script_path = "/Users/weifeng/.../inject-susfs-dispatch.py"`，GHA 容器文件系统不同，此路径不存在
**教训**：
1. 所有注入脚本中的文件路径必须使用 `os.path.join(KERNEL_ROOT, ...)` 相对路径
2. 绝对路径（`/Users/xxx/`、`/home/xxx/`）在 CI 容器中**一定会失效**
3. 构建脚本路径应该基于 `sys.argv[1]`（kernel root）计算，而非基于开发者本地目录
4. 在推送前运行 `grep -n '/Users/\|/home/' scripts/*.py` 检查是否有残留的本地路径
**检查清单锚点**：见「路径检查」项 ✅

### E009：注入代码使用了标准库中可能不存在的类型（Batch 2）
**现象**：编译报 `incomplete type 'struct st_susfs_sus_path_list'`，结构体在目标文件中未定义
**根因**：`sus_path_loop` 函数使用了 `struct st_susfs_sus_path_list`，该结构体定义在 `susfs.h` 中且仅在 hypermezo4 镜像（v1.5.9）中存在。gitlab 原始版（v1.5.5）也可能存在但具体定义不确定。GHA 构建使用 gitlab 版本
**教训**：
1. 注入脚本中使用的任何类型必须在注入代码自身中定义（或确认目标环境确实存在）
2. 不要依赖"另一个文件中有这个结构体"——GHA 的源文件版本可能不同
3. 安全做法：在注入代码中本地定义所需的结构体，使用唯一前缀名（如 `_local`）避免命名冲突
4. **即使本地定义的结构体，也不得引用外部类型作为字段**。如 `struct st_susfs_sus_path_list_local { ... struct st_susfs_sus_path info; ... }` 仍依赖 `susfs.h` 中的 `st_susfs_sus_path`。必须平铺展开所有字段，做到完全自包含
**检查清单锚点**：见「功能可行性调研」和「结构体布局与目标版本一致」项 ✅

### E008：Python 缩进不一致导致运行时报错（Batch 2）
**现象**：GHA 运行注入脚本时报 `IndentationError: unexpected indent`，build 失败
**根因**：多次 edit 命令修改 inject 脚本时，替换的代码块缩进层级与其他部分不一致（9 spaces vs 8 spaces）。本地语法检查未做就提交了
**教训**：
1. 所有 Python 代码修改后必须运行 `python3 -c \"import py_compile; py_compile.compile('scripts/xxx.py', doraise=True)\"` 检查语法
2. 用 edit 工具替换代码时，仔细核对缩进空格数是否与上下文一致
3. pre-flight-check.sh 应增加 Python 语法检查步骤
**检查清单锚点**：见「Python 语法检查」项 ✅
