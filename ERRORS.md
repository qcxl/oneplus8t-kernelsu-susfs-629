# 错误经验库

> 每次修复后在此新增条目。[cross-project] 标记的条目由 `kport evolve` 跨项目共享。

## 🧠 错误经验库（每次修复后更新）

### E001：`#define` 字符串替换缺少前缀（Batch 1）
**现象**：编译报 `macro name must be an identifier`，生成 `#define #define CMD_...`
**根因**：替换目标字符串 `'CMD_SUSFS_ADD_SUS_MAP'` 不包含前面的 `#define`，替换后变 `#define #define ...`
**教训**：替换预处理指令时必须包含完整的 `#define NAME VALUE` 行，切勿只匹配 NAME
**检查清单锚点**：见「替换丢失 `#define`」项 ✅
**标签**：cross-project

### E002：注入锚点在目标文件中不存在，静默跳过（Batch 1）
**现象**：编译报 `incomplete type / forward declaration`。struct 定义不存在，但函数声明已插入
**根因**：`inject_susfs_h()` 使用 `int susfs_get_enabled_features` 做锚点，但 GHA 实际文件中函数签名不同（本地读的是 hypermezo4 v1.5.9 镜像，GHA 用 gitlab 原始版）。插入静默失败，return True
**教训**：
1. 注入脚本必须检查插入是否成功，失败返回 False
2. 本地文件 ≠ GHA 源文件。差异源：gitlab 原始版 vs GitHub 镜像版 vs 50_add 补丁生成版
3. 使用 `/* susfs_init */` 等稳定标记做锚点（跨版本不变）
**检查清单锚点**：见「确认注入标记」和「注入脚本必须检查」项 ✅
**标签**：cross-project

### E003：多步插入产生半状态（Batch 1）
**现象**：先 `lines.insert(func)` 再 `content.replace(func, func + wrapper)`，后一步失败则只有 func 被插入
**根因**：分两步插入相关代码，没有原子性保证
**教训**：所有逻辑上必须同时存在的代码（如 struct + 声明、avc_func + enable_log_wrapper）必须合并为一次字符串后用单次插入
**检查清单锚点**：见「缩进一致性」项 ✅
**标签**：cross-project

### E004：`#ifdef` 子选项未在 Kconfig 注册（Batch 1 预防）
**潜在风险**：新增 `#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING` 保护的代码，如果 Kconfig 未注册且 ksu.config 未设置，代码被编译但选项不生效
**预防**：每次新增 `#ifdef CONFIG_*` 时，同步检查 Kconfig 配置文件（`kconfig.config_file`）和 CI 注册（`kconfig.ci.register_file`）
**检查清单锚点**：见「Kconfig 注册一致性」项 ✅
**标签**：cross-project

### E005：本地文件与 GHA 实际源文件不一致
**风险**：gitlab 原始版 vs GitHub 镜像版 vs 补丁生成版之间可能有差异。本地读的版本可能 ≠ CI 构建用的版本
**预防**：锚点/标记优先使用不易随版本变更的固定字符串，而非特定代码行。确认源文件的精确来源
**检查清单锚点**：见「文件版本差异」项 ✅
**标签**：cross-project

### E006：武断删除功能，未做可行性调研
**现象**：发现 `ksu_cred` 在预读的 KSUN 源码中未搜到，直接判定"无法移植"要删掉 `sus_path_loop`
**根因**：搜索范围不够全——`ksu_cred` 实际存在于 `kernel/include/ksu.h`，只是不在最初搜索的 `kernel/ksu.c` 中
**教训**：
1. **任何功能不得在未完成完整可行性调研前标记为"无法移植"**
2. 搜索依赖时覆盖所有可能的文件路径，不仅仅是自己认为"可能"的位置
3. 对缺失的依赖，先查 3 种可能：① 改名了在不同位置 ② 在内核头文件中 ③ 需要自己实现 shim/wrapper
4. 确认不可行后才记录原因、提交决策说明，**不可静默删除**
**检查清单锚点**：见「功能可行性调研」项 ✅
**标签**：cross-project

### E007：脚本中使用硬编码本地绝对路径（Batch 2）
**现象**：GHA 构建报 `FileNotFoundError: /Users/weifeng/...`，连续 3 次构建失败
**根因**：`patch_dispatch_template()` 中写了硬编码路径 `script_path = "/Users/weifeng/.../inject-susfs-dispatch.py"`，GHA 容器文件系统不同，此路径不存在
**教训**：
1. 所有注入脚本中的文件路径必须使用 `os.path.join(KERNEL_ROOT, ...)` 相对路径
2. 绝对路径（`/Users/xxx/`、`/home/xxx/`）在 CI 容器中**一定会失效**
3. 构建脚本路径应该基于 `sys.argv[1]`（kernel root）计算，而非基于开发者本地目录
4. 在推送前运行 `grep -n '/Users/\|/home/' scripts/*.py` 检查是否有残留的本地路径
**检查清单锚点**：见「路径检查」项 ✅
**标签**：cross-project

### E009：注入代码使用了标准库中可能不存在的类型（Batch 2）
**现象**：编译报 `incomplete type 'struct st_susfs_sus_path_list'`，结构体在目标文件中未定义
**根因**：`sus_path_loop` 函数使用了 `struct st_susfs_sus_path_list`，该结构体定义在 `susfs.h` 中且仅在 hypermezo4 镜像（v1.5.9）中存在。gitlab 原始版（v1.5.5）也可能存在但具体定义不确定。GHA 构建使用 gitlab 版本
**教训**：
1. 注入脚本中使用的任何类型必须在注入代码自身中定义（或确认目标环境确实存在）
2. 不要依赖"另一个文件中有这个结构体"——GHA 的源文件版本可能不同
3. 安全做法：在注入代码中本地定义所需的结构体，使用唯一前缀名（如 `_local`）避免命名冲突
4. **即使本地定义的结构体，也不得引用外部类型作为字段**。如 `struct st_susfs_sus_path_list_local { ... struct st_susfs_sus_path info; ... }` 仍依赖 `susfs.h` 中的 `st_susfs_sus_path`。必须平铺展开所有字段，做到完全自包含
**检查清单锚点**：见「功能可行性调研」和「结构体布局与目标版本一致」项 ✅
**标签**：cross-project

### E008：Python 缩进不一致导致运行时报错（Batch 2）
**现象**：GHA 运行注入脚本时报 `IndentationError: unexpected indent`，build 失败
**根因**：多次 edit 命令修改 inject 脚本时，替换的代码块缩进层级与其他部分不一致（9 spaces vs 8 spaces）。本地语法检查未做就提交了
**教训**：
1. 所有 Python 代码修改后必须运行 `python3 -c \"import py_compile; py_compile.compile('scripts/xxx.py', doraise=True)\"` 检查语法
2. 用 edit 工具替换代码时，仔细核对缩进空格数是否与上下文一致
3. pre-flight-check.sh 应增加 Python 语法检查步骤
**检查清单锚点**：见「Python 语法检查」项 ✅
**标签**：cross-project

### E010：dispatch 模板引用了未定义的常量（Batch 2）
**现象**：编译报 `use of undeclared identifier 'CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS'`
**根因**：`inject-susfs-dispatch.py` 模板中添加了 `CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS` 的 dispatch 条目，但 `susfs_def.h` 中只定义了同值的 `CMD_SUSFS_HIDE_SUS_MNTS_FOR_ALL_PROCS`（v1.5.5 命名）。新名字未在 `susfs_def.h` 中定义
**教训**：
1. dispatch 模板中引用的任何 CMD 常量，必须在注入脚本中同步添加其定义
2. 当 v2.2.0 重命名了常量但值不变时（0x55561），需在 v1.5.5 中添加别名定义
3. 全链路追踪必须从 dispatch 条目到常量定义全覆盖——dispatch.c 编译时引用的所有符号都要可解析
**检查清单锚点**：见「全链路追踪」和「Kconfig 一致性」项 ✅
**标签**：cross-project

### E011：extern 变量在链接时找不到定义（Batch 2）
**现象**：链接报 `undefined symbol: susfs_hide_sus_mnts_for_all_procs`
**根因**：`susfs.c` 中用 `extern` 声明了 `susfs_hide_sus_mnts_for_all_procs`，该变量定义在 `fs/proc_namespace.c` 中（50_add 补丁添加）。但链接器找不到该符号——可能是因为 `obj-$(CONFIG_PROC_FS)` 条件编译或模块分离导致
**教训**：
1. 跨文件的 `extern` 全局变量在链接时可能不可靠，尤其当定义在条件编译的文件中
2. 优先在同一个 `.c` 文件中定义变量，然后通过 patch 移除其他文件中的重复定义
3. 链接错误 `undefined symbol` 和编译错误 `incomplete type` 是不同层面的问题
**可自动化**：no
**对应检查**：无法自动化（需要人为判断变量定义位置）
**检查清单锚点**：见「功能可行性调研」项 ✅
**标签**：cross-project

### E013：dispatch 模板 show_enabled_features 的 #ifdef 块不完整
**现象**：`ksud susfs features` 只报告部分功能（如仅 SUS_PATH），但 `.config` 中所有功能都已编译为 `=y`，boot.img 中也能找到真实实现的日志字符串。
**根因**：`inject-susfs-dispatch.py` 中 `CMD_SUSFS_SHOW_ENABLED_FEATURES` 的 `#ifdef` 块只有 10 个，缺少 6 个（AVC_LOG / SUS_PATH_LOOP / OVERLAYFS / 3 个 AUTO_ADD）。`copy_to_user` 的字符串字面量未嵌入二进制 → `ksud susfs features` 不会报告。
**教训**：
1. 功能编译与否（`.config`）和功能报告与否（`show_enabled_features` 的 `#ifdef` 块）是独立的两层，必须同步更新
2. inject 脚本中 IOCTL handler 和 reboot handler 两处都要更新相同的 `#ifdef` 块
3. 验证功能是否完整时，不只靠 `ksud susfs features`，还要检查 `.config` + boot.img 字符串
**锚点**：FLOW.md §3 全链路追踪 — CMD 常量完整性
**标签**：cross-project

### E015：#ifndef CONFIG_KSU_SUSFS 误杀无真实实现的 stub 函数
**现象**：编译成功但链接失败，报 `undefined symbol: susfs_is_current_ksu_domain / susfs_is_current_zygote_domain / ksu_try_umount / susfs_try_umount_all`。
**根因**：`susfs_stubs.c` 中用 `#ifndef CONFIG_KSU_SUSFS` 包裹所有 stub 函数。但其中 4 个函数没有对应的真实实现（仅在 50_add patch 中定义，patch 不一定总能干净应用）。`#ifndef` 移除了它们后，链接器找不到符号。
**教训**：
1. 用 `#ifndef` 包裹 stub 前，必须确认每个被包裹的函数是否存在真实实现
2. 判断方法：在 `susfs.c`（上游）、inject 脚本、50_add patch 中分别搜索函数名
3. 没有真实实现的函数，stub 必须无条件保留
**锚点**：FLOW.md §1b 依赖追踪 — 全局变量搜索覆盖范围
**标签**：cross-project

### E017：共享函数跨文件调用时缺 extern 声明（已修复）
**现象**：编译报 `implicit declaration of function 'susfs_show_features'`。
**根因**：`susfs_show_features()` 在 dispatch.c 中定义为 `static`，但在 supercall.c 中被调用。同一模块的不同编译单元不能共享 `static` 函数，且 supercall.c 中缺少 `extern` 声明。
**教训**：
1. 被多个 .c 文件调用的函数不能 `static`，必须全局可见
2. 调用方需要 `extern` 声明
3. inject 脚本中定义的函数要考虑最终插入到哪个 .c 文件、被哪些文件调用
**锚点**：FLOW.md §1c 全链路追踪 — 功能可行性调研
**标签**：cross-project

### E016：dispatch 模板引用了 v1.5.5 中不存在的函数
**现象**：编译报 `implicit declaration of function 'susfs_add_sus_kstat_statically'`。
**根因**：`CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY` 是 v2.2.0 新增的 CMD，调用 `susfs_add_sus_kstat_statically()` 函数。但 v1.5.5 中没有此函数，只有 `susfs_add_sus_kstat()`（通过 inode 编号添加，非通过路径名静态添加）。
**教训**：
1. 添加 dispatch 条目前，必须先确认目标函数在内核中存在（搜索 susfs.c + susfs.h）
2. v2.2.0 新增的 CMD 不一定对应 v1.5.5 中存在的函数。CMD 常量可以从 susfs_def.h 复制，但 handler 函数需要从源码确认
3. 通过 `grep -E '^(int|void|bool).*function_name' susfs.c susfs.h` 验证函数原型是否存在
**锚点**：FLOW.md §1c 全链路追踪 — 功能可行性调研
**标签**：cross-project

### E014：copy_to_user 字符串长度错误导致 features 错位（已修复）
**现象**：`ksud susfs features` 只返回 `CONFIG_KSU_SUSFS_SUS_PATH`，但 `strings boot.img | grep CONFIG_KSU_SUSFS_` 显示全部 16 个功能字符串存在。`/kport flash` 测试内核返回的原始数据发现后续功能出现字节错位（如 `CCONFIG_KSU_SUSFS_SUS_MOUNT` 开头多了个 C）。
**根因**：`inject-susfs-dispatch.py` 中 `copy_to_user` 的字符串长度参数比实际 C 字符串长度多 1-2 字节。例如 `CONFIG_KSU_SUSFS_SUS_PATH\n` 实际 26 字节但代码写 28。多出的字节包含了后续字符串开头的字符，导致 `pos` 计算偏移，后续功能错位。
**教训**：
1. C 字符串长度 = 可见字符数 +1(`\n`)。不能用 `len(python_string)` 计算（Python 中 `\n` 是 1 字节但 `\\n` 是 2 字节）
2. 验证 feature 完整性的可靠方式：用测试工具直接读内核返回的原始缓冲区（`strings boot.img` 只证明字符串被编译，不证明运行时正确返回）
3. 修复后验证：32 处 `copy_to_user`（16 功能 × IOCTL+reboot 两处）全部手动校验长度
**锚点**：FLOW.md §2 代码审计 — Dispatch 条目
**标签**：cross-project

### E012：GHA workflow Kconfig 注册缓存导致新功能配置被静默丢弃
**现象**：在 ksu.config 中新增了 `CONFIG_KSU_SUSFS_SUS_PATH_LOOP=y` 等配置项，编译成功但 boot.img 中没有这些功能，`ksud susfs features` 只显示旧功能。
**根因**：GHA workflow 中使用 `if grep -q "config KSU_SUSFS" ...; then echo "Already present, skipping"` 检查 Kconfig 文件是否已有 SUSFS 条目。如果之前已有旧条目（如基础 10 个），新条目的注册被整个跳过。`merge_config.sh` 遇到 ksu.config 中定义的选项但 Kconfig 中没有注册时，静默丢弃该选项。结果 .config 不变 → ccache 命中 → 输出不变。
**教训**：
1. Kconfig 注册代码不能使用"存在就跳过"的缓存逻辑。必须每次重新生成所有条目（先删除旧 SECTION 再追加全部新条目）
2. `merge_config.sh` 静默丢弃未注册的 Kconfig 选项，不会报错。必须通过 `grep CONFIG_KSU_SUSFS_ out/.config | sort` 在 GHA 日志中显式打印验证
3. 改 workflow / ksu.config / inject 脚本后，ccache 可能复用旧缓存。需设置 `CCACHE_EXTRAFILES` 包含这些文件，确保变更时自动缓存失效
4. `|| true` 掩盖了 patch/clone 失败。应改用 `|| echo WARNING` 或显式检查
**锚点**：FLOW.md §2 代码审计 — Kconfig 一致性检查
**标签**：cross-project

### E018：SUSFS gitlab clone 间歇性网络失败
**现象**：GHA 构建报 `ERROR: SUSFS clone failed!`，`/tmp/susfs/kernel_patches` 目录不存在，构建立即退出 1。
**根因**：`git clone https://gitlab.com/simonpunk/susfs4ksu.git` 在 GHA runner 上间歇性网络超时（~20% 概率），gitlab.com 对中国大陆/部分区域的 CI 访问不稳定。
**教训**：
1. `exit 1` 直接终止整个构建，应该加重试循环。已改为 `for i in 1 2 3; do ... done` 最多重试 3 次
2. `|| true` 掩盖问题不应直接 exit 1，但 clone 失败后续步骤确实无法进行，所以 retry 比 exit 更合理
3. 长期方案：将 SUSFS 源码镜像到 GitHub（如 `qcxl/susfs4ksu-mirror`）避免依赖 gitlab.com
**锚点**：FLOW.md §1e 常见失败模式 — CI 步骤顺序

### E019：fix-ksu-uapi-v2.py 路径和 pattern 错误
**现象**：GHA 构建报 `ERROR: supercall.h not found` 和 `ERROR: GET_INFO table entry end not found`，fix-ksu-uapi-v2.py 两个函数均返回 False 并 exit 1。
**根因**：
1. `supercall.h` 不在脚本检查的路径中。setup.sh 创建 symlink `drivers/kernelsu/ → ../KernelSU-Next/kernel/`，但 `uapi/supercall.h` 在 `KernelSU-Next/uapi/`（仓库根目录），不在 `kernel/` 子目录。脚本只检查了 `drivers/kernelsu/uapi/supercall.h` 和 `KernelSU/kernel/uapi/supercall.h`（连名字都拼错了，应该是 `KernelSU-Next`）
2. `GET_INFO table entry end not found` 原因是匹配 pattern 用了 4 空格缩进 `    {`，但 legacy dispatch.c 使用 `\t{`（tab）
3. 插入逻辑 `content[:P] + ',\n' + entry + content[P:]` 在 `},` 前后各加一次，导致双 `},\n},\n` 语法错误
**教训**：
1. 路径搜索应使用 `find_file()` 封装函数，枚举所有可能路径
2. dispatch.c 的缩进风格混合了 tab 和空格，必须用 regex 匹配
3. 插入到 struct 数组时用 `match.start() + 2`（跳过 `},`），不要在插入内容中加多余的逗号
**锚点**：FLOW.md §1e 常见失败模式 — 文件版本差异 / 缩进不一致

### E020：Python \n 被解释为换行符写入 C 文件
**现象**：GHA 编译报 `missing terminating '"' character`，dispatch.c 中 `pr_err("get_version: copy_to_user failed` 字符串缺少闭合双引号。
**根因**：`fix-ksu-uapi-v2.py` 中用 Python 三引号 `'''...'''` 定义 `do_get_info_legacy` C 代码模板。字符串中的 `\n` 被 Python 解析为换行符，导致 C 代码中：`pr_err("get_version: copy_to_user failed\n");` → 输出为 `pr_err("get_version: copy_to_user failed` + 换行 + `");` 语法错误。
**教训**：
1. Python 三引号中 `\n`、`\t` 会被解析，写 C 代码模板必须用 `r'''...'''`（raw string）
2. `pr_err()` 等 C 字符串中的 `\n` 必须保持为字面量 `\n`，原始字符串自动保留
3. 此类问题应在本地 `py_compile` + `grep \\\\n' 脚本输出` 前发现
**锚点**：FLOW.md §1d 边界验证 — 缩进一致

### E021：struct kstatfs 未声明导致编译失败
**现象**：GHA 编译报 `error: field has incomplete type 'struct kstatfs'`，位置在 `susfs.h:117`，`st_susfs_open_redirect_hlist` 结构体中的 `spoofed_kstatfs` 字段。
**根因**：`struct kstatfs` 定义在 `<linux/statfs.h>` 中。注入脚本在 `susfs.h` 中新增了带 `struct kstatfs` 字段的结构体，但 `susfs.h` 未包含 `<linux/statfs.h>`。v1.5.5 的 `susfs.h` 只包含了 `<linux/fs.h>`，而 `struct kstatfs` 在 4.19 上并非从 `fs.h` 间接引用得到。
**教训**：
1. 任何新增的 struct 字段类型必须确认其头文件已包含
2. 4.19 上 `struct kstatfs` 需要显式 `#include <linux/statfs.h>`
3. 结构体变化应在注入脚本中同步更新头文件的 include 列表
**锚点**：FLOW.md §1a 源码阅读 — 结构体依赖追踪

### E021v2：statfs.h include 追加失败（replace 可能未匹配）
**现象**：第一次修复后依然报 `error: field has incomplete type 'struct kstatfs'`。
**根因**：`c.replace("#include <linux/fs.h>", ...)` 假设 v1.5.5 的 `susfs.h` 含有 `#include <linux/fs.h>`，但该头文件可能根本没有这一行（50_add patch 产生的 `susfs.h` 内容不确定）。`replace()` 未匹配则静默失败，include 未添加。
**教训**：不要用 `replace()` 假设特定 include 行存在。改用「找最后一个 `#include` 行追加」模式更鲁棒。
**锚点**：FLOW.md §1e 常见失败模式 — 静默跳过

### E022：4.19 无 do_sys_openat2，openat 钩子不可移植
**现象**：编译报 `use of undeclared identifier 'is_inode_open_redirect'` + `use of undeclared identifier 'INODE_STATE_OPEN_REDIRECT'` + `incompatible pointer types passing to 'void **'`。
**根因**：
1. `do_sys_openat2()` 是 Linux 5.6 才引入的。4.19 Lineage 内核没有此函数。注入脚本向 `fs/open.c` 插入的 `do_sys_openat2` retry 逻辑找不到函数定义，retry label 和变量声明插错位置，`is_inode_open_redirect` 未声明。
2. `inject-susfs-dispatch.py` 在 `supercall.c`（reboot handler）中写了旧签名 `susfs_add_open_redirect(结构体*)`，但 `inject-open-redirect-enhanced.py` 只更新了 `dispatch.c`，漏了 `supercall.c`。
**教训**：
1. 注入 VFS 钩子前必须确认目标函数在内核中存在——4.19 与 6.1 的函数签名差异很大
2. 注入脚本必须同时修复 `dispatch.c`（IOCTL 表）和 `supercall.c`（reboot 分发器）两处
3. 开新任务前应先 `/kport verify` 检查目标函数存在性
**锚点**：FLOW.md §1a 源码阅读 — 确认目标函数存在
