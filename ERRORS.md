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

### E023：do_filp_open 锚点缩进不匹配导致 spoof 代码静默缺失

**现象**：`../fs/open.c:1099:7: error: unused variable 'is_inode_open_redirect' [-Werror,-Wunused-variable]`。`is_inode_open_redirect` 被声明但编译器报未使用。

**根因**：`inject-open-redirect-enhanced.py` 用 3 个独立锚点修改 `fs/open.c` 的 `do_sys_open`：
1. 函数签名 `long do_sys_open(...)\n{` → 注入变量声明 ✅
2. `\tfd = get_unused_fd_flags(flags);` → 注入 `retry:` 标签 ❌ 锚点不匹配
3. `\t\tstruct file *f = do_filp_open(dfd, tmp, &op);` → 注入 spoof 代码 ❌ 锚点不匹配

第 2/3 步锚点的缩进（空格 vs tab）与 LineageOS 4.19 源文件不一致，`c.replace()` 静默失败。变量声明了但从未使用，`-Werror` 杀死构建。

**教训**：
1. **永远不要依赖确切的空格/tab 缩进做锚点匹配**。不同内核版本/厂商的缩进习惯不同
2. 使用函数签名做唯一锚点，**一次替换整个函数体**，确保原子性
3. 分隔为多个 `c.replace()` 时，每个都必须检查返回值——`str.replace()` 没匹配到返回原字符串，后续代码用的还是旧内容

**修复**：将 variable + retry + spoof 全部合并为**一次原子替换**，锚定在 `long do_sys_open(...)\n{` 这一个唯一稳定的点上，函数体按 LineageOS 4.19 实际的 body 重新生成。

**锚点**：FLOW.md §1e 常见失败模式 — 静默跳过 / 缩进不一致

**标签**：cross-project

### E024：susfs_add_open_redirect 声明了未使用的 `bkt` 变量

**现象**：`../fs/susfs.c:1051:6: error: unused variable 'bkt' [-Werror,-Wunused-variable]`。

**根因**：`inject-open-redirect-enhanced.py` 注入的 `susfs_add_open_redirect` 函数中声明了 `int bkt;`，此变量用于 `hash_for_each_possible_safe` 宏。但 4.19 的 `hash_for_each_possible_safe` 宏原型是 `(name, obj, tmp, member, key)`，不包含 `bkt` 参数。该宏实现为 `hlist_for_each_entry_safe` 的单桶搜索，不需要桶索引变量。`bkt` 仅被旧版内核或 `hash_for_each_safe`（非"possible"版本）所需。

**教训**：
1. 每个宏的签名在不同内核版本间可能有差异，不能假设 6.1 的宏在 4.19 上相同
2. 声明宏所需的辅助变量前，搜索目标内核版本中该宏的实际定义
3. 4.19 `<linux/hashtable.h>` 中的宏定义明确不需要 `bkt`

**修复**：删除 `int bkt;` 声明。

**锚点**：FLOW.md §1c 全链路追踪 — 确认目标函数签名

**标签**：cross-project

### E025：open_redirect spoof 函数引用了 v1.5.5 中不存在的 `susfs_is_current_proc_umounted_app`

**现象**：`../fs/susfs.c:1123:10: error: implicit declaration of function 'susfs_is_current_proc_umounted_app'`。

**根因**：`susfs_open_redirect_spoof_do_sys_openat` 的 `UID_SCHEME` switch 中有 `case UID_UMOUNTED_APP_PROC`，调用了 `susfs_is_current_proc_umounted_app()`。此函数是 SUSFS v2.2.0 新增的，v1.5.5 中只有 `susfs_is_current_proc_umounted()`，没有对应的 `_app` 变体。

**教训**：
1. v2.2.0 新增的功能函数不一定在 v1.5.5 中存在。添加 dispatch 条目时必须先确认 handler 函数存在
2. 缺失的函数需要无条件 stub（放置在 `#ifndef CONFIG_KSU_SUSFS 之外`），因为实时代码路径在 `#ifdef CONFIG_KSU_SUSFS` 中
3. stub 语义：返回 `false`（不匹配任何重定向条目），上层调用者会回退到原路径

**修复**：在 `susfs_stubs.c` 的 always-needed 段中添加 `susfs_is_current_proc_umounted_app()` stub（返回 false）。

**锚点**：FLOW.md §1c 全链路追踪 — 功能可行性调研

**标签**：cross-project

### E022：4.19 do_sys_open 与 6.1 do_sys_openat2 签名不同
**现象**：编译报 `undeclared identifier 'is_inode_open_redirect'` + `undeclared identifier 'INODE_STATE_OPEN_REDIRECT'` + `incompatible pointer types passing to 'void **'`。
**根因**：
1. `do_sys_openat2(dfd, filename, open_how*)` 是 Linux 5.6 引入的。4.19 用 `do_sys_open(dfd, filename, flags, mode)`，调用 `get_unused_fd_flags(flags)` 而非 `get_unused_fd_flags(how->flags)`。注入脚本用 5.6 的签名搜索 4.19 的函数，找不到则变量声明不插入，导致 `is_inode_open_redirect` 未声明。
2. `inject-susfs-dispatch.py` 在 `supercall.c`（reboot handler）中写旧签名，修复脚本只更新了 `dispatch.c`，漏了 `supercall.c`。
**教训**：
1. VFS 钩子必须逐内核版本确认函数签名——2018 的 4.19 和 2024 的 6.1 差异极大
2. 4.19 的 do_sys_open 签名是 `(int dfd, const char __user *filename, int flags, umode_t mode)`，不是 `(int dfd, const char __user *filename, struct open_how *how)`
3. dispatch 需要同时更新 `dispatch.c`（IOCTL 表）和 `supercall.c`（reboot 分发器）两处
4. 先 `/kport trace` 确认目标函数在 4.19 上的真实签名再写注入脚本
**修复**：改用 4.19 签名模式搜索 `do_sys_open` 并插入变量/retry/spoof。保留全部功能。
**锚点**：FLOW.md §1a 源码阅读 — 确认目标函数签名

### E026：selinux.h 用 struct policydb* 参数导致 -Wvisibility 编译失败

**现象**：编译报 `error: declaration of 'struct policydb' will not be visible outside of this function [-Werror,-Wvisibility]`，`selinux.h:52`，出错文件 `drivers/kernelsu/core/init.o`。

**根因**：`selinux.h` 被注入 `void ksu_selinux_save_backup(struct policydb *db);`。`init.c` 包含 `selinux.h` 但无权访问 `security/selinux/ss/policydb.h`。GCC 将参数中的 `struct policydb` 视为前向声明，仅在该函数声明作用域内可见，`-Wvisibility` + `-Werror` 将其升级为编译错误。

**教训**：
1. KSU 的 `selinux.h` 会被 KSU core 文件（如 `init.c`）包含，这些文件无权访问 kernel 内部 `struct policydb`
2. 跨模块暴露内部 SELinux 类型时必须用 `void *`，实现处强制转换
3. GHA 验证路径也必须用 `drivers/kernelsu/selinux/` 前缀

**修复**：`selinux.h` 声明改为 `void ksu_selinux_save_backup(void *db);`，实现处 `void ksu_selinux_save_backup(void *src_db_v) { struct policydb *src_db = src_db_v; ... }`

**锚点**：FLOW.md §1d 边界验证 — 符号冲突 / 内核版本兼容

**标签**：cross-project

### E027：static 函数 ksu_backup_policydb 在不同编译单元不可见

**现象**：编译报 `error: implicit declaration of function 'ksu_backup_policydb' [-Werror,-Wimplicit-function-declaration]`，`selinux.c:414`。

**根因**：`ksu_backup_policydb()` 定义为 `static` 并通过 `BACKUP_SEPOLICY` 注入到 `sepolicy.c`，但其调用者 `ksu_selinux_save_backup()` 在 `SELINUX_HIDE_CORE` 中注入到 `selinux.c`。两个不同的 `.c` 文件分别编译为独立的目标文件（`.o`），`static` 函数不出现在符号表中，链接器无法解析。

**教训**：
1. `static` 函数仅在定义它的编译单元内可见，不可跨 `.c` 文件调用
2. 逻辑上属于同一功能模块的代码应注入到同一个 `.c` 文件中，避免跨文件依赖
3. 注入脚本中关联的函数（backup + core）应放在同一个 snippet 中

**修复**：将 `ksu_backup_policydb` 从 `BACKUP_SEPOLICY` 移入 `SELINUX_HIDE_CORE`，全部注入到 `selinux.c`。删除 `sepolicy.c` 的注入步骤。

**锚点**：FLOW.md §1c 全链路追踪 — 功能可行性调研

**标签**：cross-project

### E028：合入 selinux.c 后缺 policydb.h 头文件 → 应回归 sepolicy.c + extern void*

**现象**：编译报 `fatal error: 'security/selinux/ss/policydb.h' file not found` 或 `implicit declaration of function 'policydb_init'`。

**根因**：
1. 试错方案1：用 `#include <security/selinux/ss/policydb.h>` — 该头文件在 kernel 4.19 中属于 SELinux 内部（`security/selinux/ss/`），不在公开 include path 中，编译找不到
2. 试错方案2：将 `ksu_backup_policydb` 移入 `selinux.c` — 该文件无权访问 `struct policydb` 及 `policydb_*` 函数，因为 `security/selinux/ss/policydb.h` 不对外暴露

**教训**：
1. SELinux 内部头文件（`security/selinux/ss/`）不可从外部驱动包含。这不是 include path 问题，是内核架构限制
2. 使用 SELinux SS 层类型的代码必须放在 KSU 的 `sepolicy.c` 中（该文件通过 `ss/services.h` 间接获得类型）
3. 跨文件调用时：定义方用具体类型（`struct policydb *`），调用方在 extern 声明中用 `void *`
4. C 语言中 `void *` ↔ T* 的隐式转换在 extern 声明中完全合法，链接器按符号名解析即可

**修复**：`ksu_backup_policydb` 回到 `BACKUP_SEPOLICY` 注入 `sepolicy.c`，去掉 `static`。`SELINUX_HIDE_CORE` 中加 `extern void *ksu_backup_policydb(void *src);`。保持 `ksu_selinux_save_backup` 用 `void *src_db_v` cast。

**锚点**：FLOW.md §1d 边界验证 — 符号冲突 / 内核版本兼容

**标签**：cross-project

**现象**：编译报 `error: implicit declaration of function 'policydb_init' [-Werror,-Wimplicit-function-declaration]`，`selinux.c:411`。

**根因**：`ksu_backup_policydb()` 移入 `SELINUX_HIDE_CORE`（注入 `selinux.c`）后，需要 `policydb_init/policydb_write/policydb_read/policydb_destroy` 等函数。这些函数声明在 `<security/selinux/ss/policydb.h>` 中，但注入代码只包含了 `ss/services.h`（KSU 本地），未包含该头文件。

**教训**：
1. 跨编译单元移动代码时，必须同步检查头文件依赖是否完整
2. `sepolicy.c` 能编译通过不一定是因为其显式 include，可能是因为它间接从其他 include 链获得了类型
3. `policydb_*` 系列函数在 4.19 上位于 `security/selinux/ss/`，KSU 作为 `obj-y` 内建驱动可在链接时访问这些符号，但编译期仍需要显式 include

**修复**：`SELINUX_HIDE_CORE` 增加 `#include <security/selinux/ss/policydb.h>`

**锚点**：FLOW.md §1d 边界验证 — 内核版本兼容

**标签**：cross-project

### E029：policydb_* 在 4.19 上不可从 KSU 模块调用 → Route A only

**现象**：即使注入 `sepolicy.c`（KSU selinux 模块），仍报 `implicit declaration of function 'policydb_init'`。E026-E028 三轮回退后确认此根本限制。

**根因**：`policydb_init/write/read/destroy` 是 SELinux SS 内部函数，声明在 `security/selinux/ss/policydb.h`。该头文件在 kernel 4.19 上仅对 `security/selinux/` 内部可见，`drivers/kernelsu/selinux/` 无权访问。

**决策**：缩减为 **Route A only**（仅 setprocattr hook），不依赖 `policydb_*`，不备份。
- Route B（context/access + backup）标记为 "4.19 不可行"

**教训**：任何涉及 `policydb_*` 的代码都不能在 KSU 模块编译通过。GLM HTML 报告的完整方案假设了这些函数可访问，实际 4.19 上不行。

**修复**：删除 BACKUP_SEPOLICY / SELINUX_RULES_BACKUP / SELINUX_H_DECL。仅注入 `selinux.c`（setprocattr hook）+ `feature.h`（UAPI 枚举）。

**锚点**：FLOW.md §1b 依赖追踪 — 外部函数可用性确认

**标签**：cross-project

### E030：selinux_hide handler 未注册导致被编译器优化掉（死代码消除）

**现象**：编译通过，刷机后 `kallsyms` 无 `ksu_selinux_hide` 符号，`ksud feature list` 不显示 ID=5 功能。

**根因**：`static const struct ksu_feature_handler selinux_hide_handler` 没有任何代码引用它。虽然定义在源文件中，但编译器做死代码消除（dead code elimination）将其完全移除。KSU 的 feature 机制需要显式调用 `ksu_register_feature_handler()` 注册。

**教训**：
1. `static const` 结构体如果没有被任何函数引用（直接或通过 initcall 间接），编译器会将其视为死代码
2. KSU feature handler 必须通过 `ksu_register_feature_handler()` 注册，不能仅靠定义结构体
3. 验证方法：刷机后用 `cat /proc/kallsyms | grep ksu_selinux_hide` 或 `ksud feature list` 检查

**修复**：添加 `static int __init ksu_selinux_hide_init(void) { return ksu_register_feature_handler(&selinux_hide_handler); } postcore_initcall(ksu_selinux_hide_init);` 确保 init 时注册。

**锚点**：FLOW.md §2 代码审计 — 注入代码完整性

**标签**：cross-project

### E031：ksud 用户态不识 ID=5 → auto-enable 绕过

**现象**：内核 `dmesg` 确认 `registered handler for selinux_hide (id=5)`，但 `ksud feature set 5 1` 报 `Unknown feature: 5`。符号在 kallsyms 中可见，特征无法从用户态启用。

**根因**：ksud（`feature.rs`）的 `FeatureId::from_u32()` 有硬编码白名单（ID 0-4, 10003），ID=5 不在其中。KSU-Next v3.2.0 的 `SelinuxHide=4` 与 legacy 的 `selinux_hide_status=4` 冲突。Rust 编译的 ksud 无法简单 hex patch。

**教训**：
1. KSU FeatureId 在 userspace (ksud) 和 kernel 各有硬编码列表
2. legacy 新增 feature ID 需同步更新 ksud 源码
3. 编译 ksud 需要 Rust + NDK，受限环境不可行

**修复**：`ksu_selinux_hide_init()` 在注册 handler 后额外调用 `hook_selinux_setprocattr()` + 设置 `ksu_selinux_hide_enabled = true` 自启用。

**锚点**：FLOW.md §1b — 用户态工具支持

**标签**：cross-project

### E033：ksu_feature_init 在 device_initcall 清空 feature_handlers

**现象**：`dmesg` 显示 `registered handler for selinux_hide (id=5)`，但 `ksud-new feature set 5 1` 报 `EOPNOTSUPP`。

**根因**：`ksu_feature_init()` 在 `module_init`（≈ `device_initcall`，level 6）阶段将 `feature_handlers[0..KSU_FEATURE_MAX]` 全部置 NULL。注入的 `postcore_initcall`（level 2）先于 KSU 的 `device_initcall` 执行，注册的 handler 指针被后续清零。

**教训**：
1. KSU feature handler 必须注册在 **`ksu_feature_init()` 之后**，即 `late_initcall`（level 7）或更晚
2. `postcore_initcall` 虽保证 init 顺序靠前，但可能被同模块的后续初始化破坏
3. `dmesg` 注册成功 + kallsyms 符号可见 ≠ 功能可用（可能被后续代码覆盖）

**修复**：`postcore_initcall` → `late_initcall`

**锚点**：FLOW.md §1b — 锁机制 / init 顺序

**标签**：cross-project

### E034：unhook_selinux_setprocattr 运行时崩溃

**现象**：`ksud feature set 5 0` 触发 `unhook_selinux_setprocattr` 后设备立即崩溃，PMIC 记录 Unknown power-off reason。

**根因**：`unhook_selinux_setprocattr()` 在运行时试图将 `security_hook_heads.setprocattr` 的 hook 指针恢复为 `orig_setprocattr`。但此时可能有其他进程正在通过该 hook 调用，导致竞争条件或空指针解引用。该 hook 在内核中跨多进程共享，直接替换指针是危险的。

**教训**：
1. security_hook_heads 的 hook 指针在运行时不应替换为可能在后续失效的地址
2. 运行时 toggle 应通过标志位（`ksu_selinux_hide_enabled`）控制，而非物理替换 hook 指针
3. `ksu_selinux_hide_running` 标志确保 hook 只安装一次（不重复），而 `enabled` 标志控制实际行为
4. 禁用路径只需清除 `enabled` 标志，hook 会通过 `my_setprocattr` 的 if 判断直接放行

**修复**：移除 `unhook_selinux_setprocattr`、`selinux_hide_disable`、`selinux_hide_enable`。set handler 中仅控制标志位 + 一次性的 hook 安装。

**锚点**：FLOW.md §1c — 竞争条件 / 锁机制

**标签**：cross-project

### E032：Python 三引号字符串中 `\n` 被解析为换行符，C 字符串截断

**现象**：编译报 `error: missing terminating '"' character [-Werror,-Winvalid-pp-token]`，pr_info/pr_err 字符串未闭合。

**根因**：`ksu_selinux_hide_init` 新增的两个 pr_info/pr_err 中用了 `\n`（单反斜杠）。Python 三引号 `"""..."""` 中 `\n` 会被解释为换行符而非字面量。写入 C 文件后字符串中间出现真实换行，双引号提前闭合。

**教训**：
1. Python 三引号内的 `\n` 必须写 `\\n` 才能在 C 代码中生成字面量 `\n`
2. 之前 16 个 pr_* 调用全部用 `\\n` 正确，新增的 2 个遗漏了
3. 此问题在本地 `py_compile` 检查中不报错，只有 GHA 编译时暴露

**修复**：`\n` → `\\n`

**锚点**：FLOW.md §1d — 缩进一致

**标签**：cross-project

### E035：GLM 生成的 remove_avtab_node 未适配 4.19 flex_array avtab

**现象**：编译报 `error: assigning to 'struct flex_array' from incompatible type 'struct avtab_node *'`，位置在 `sepolicy.c` 第 55/62/71 行。

**根因**：GLM 5.2 生成 `remove_avtab_node()` 时假设 `struct avtab` 的 `htable` 是 `struct avtab_node **`（dev 分支 5.10+ 的做法）。但 4.19 上 `struct avtab { struct flex_array *htable; ... }`，访问元素需用 `flex_array_get()`，写入需用 `flex_array_put_ptr()`。

**教训**：
1. GLM/AI 生成的代码基于 dev 分支（5.10+）的 API，移植到 4.19 时 flex_array 适配必须手动处理
2. 4.19 SELinux 的 avtab 使用 `struct flex_array *htable`（元素 = `struct avtab_node *` 指针），不是直接指针数组
3. 读取：`(struct avtab_node *)flex_array_get(htable, idx)`
4. 写入：`flex_array_put_ptr(htable, idx, ptr, GFP_ATOMIC)`
5. 删除节点后必须先置 `n->next = NULL` 再放入 temp avtab，否则 `avtab_destroy` 会顺着 next 指针释放整个链表

**修复**：替换 `htable[i]` 为：
- 读取：`(struct avtab_node *)flex_array_get(db->te_avtab.htable, i)`
- 写入：`flex_array_put_ptr(db->te_avtab.htable, i, n->next, GFP_ATOMIC)`

**锚点**：FLOW.md §1e 常见失败模式 — 内核版本兼容

**标签**：cross-project

### E036：注入脚本锚点被上游分支更新无声破坏
**现象**：GHA 构建在 `Inject selinux_hide` 步骤失败，报 `ERROR: could not find ksu_selinux_hide_status_init() anchor`，注入脚本返回 exit 1。
**根因**：上游 KSU-Next legacy 分支于 430a739 将 `init.c` 中 `ksu_selinux_hide_status_init()` 重命名为 `ksu_selinux_hide_init()`。项目注入脚本的精确锚点匹配找不到该模式。灵活回退也因函数名变更而失败。
**教训**：
1. 项目通过 `curl setup.sh | bash -s legacy` 在 GHA 运行时拉取最新 legacy 源码，上游 commit 随时可能改变目标文件结构。
2. 注入脚本应使用更稳定的锚点（如标记注释）替代精确函数名+缩进匹配。
3. 注入尽量在已有标记基础上做幂等检查，避免重复注入。
4. 新注入步骤应放在已有注入步骤之后，防止新步骤修改文件结构破坏旧步骤的锚点。
**检查清单锚点**：GHA 注入顺序 — 新步骤加在已有步骤之后
**标签**：cross-project

### E037：注入脚本混合缩进匹配失败（tab vs space）
**现象**：编译报 `use of undeclared label 'append_module_rc'`，`goto` 已注入但目标 label 注入失败。同时 ksu_apply_init_rc_proxy 和 manual fstat 的锚点也静默跳过。
**根因**：legacy `ksud_integration.c` 混合使用 tab 缩进（read_proxy 系列）和 4-space 缩进（ksu_apply_init_rc_proxy 系列）。注入脚本只用了 tab 锚点，space 缩进的部分全部匹配失败。此外 read_proxy 结尾 `return ret;` 前有一个空行，read_iter_proxy 没有，锚点漏掉了这个差异。
**教训**：
1. 注入前用 `grep -c $'^[ ]' target.c` 确认目标文件缩进风格
2. 混合缩进文件要做 tab/space 两种 fallback
3. goto + label 必须同时注入，否则编译不通过
4. 注入脚本日志应输出到 GHA 便于排查
**检查清单锚点**：注入脚本混合缩进
**标签**：cross-project

### E038：注入脚本与上游更新后的 adb_root 冲突（redefinition + 参数数量）
**现象**：编译报 `redefinition of 'escape_to_root_for_adb_root'` 和 `too few arguments to function call, expected 3, have 2`，均在 `drivers/kernelsu/selinux/selinux.c`。
**根因**：上游 430a739 将 dev 的 `escape_to_root_for_adb_root()` 和 3 参数 `transive_to_domain()` 同步到了 legacy。但 inject-adb-root.py 仍按旧版 2 参数注入，导致函数重定义+签名不匹配。
**教训**：
1. 所有注入脚本必须做「目标功能是否已存在」的检测，存在则跳过注入
2. legacy 更新 430a739 同步了 adb_root/sulog/selinux_hide 到 legacy 基线。这些功能对应的注入脚本可能出现重定义
3. 修复后加 SCRIPT_MARK 标记防止幂等问题
**检查清单锚点**：注入前检测目标功能是否已存在
**标签**：cross-project

### E039：预存 section mismatch 导致延迟 panic
**现象**：`fastboot boot` 新内核后设备正常进入桌面，约 4 分钟后自动关机进入 fastboot。dmesg 无 panic/BUG/Oops 日志（ramoops 在 sm8250 复位后被清零）。PMIC 关机原因为 PS_HOLD 正常关机。系统恢复原始 boot 后正常。
**根因**：`WARNING: modpost: Found 6 section mismatch(es)` 预存于成功构建中（build #184 也存在）。非 __init 代码引用了 __init 标记的函数/数据，init 内存释放后访问触发 panic。`reboot=panic_warm` 导致 warm reboot 进入 fastboot。
**教训**：
1. section mismatch 虽然不阻止编译，但在运行时可能导致延迟 panic
2. sm8250 上 ramoops 不跨复位保留，panic 日志无法获取
3. 启用 `CONFIG_DEBUG_SECTION_MISMATCH=y` 获取具体 mismatch 详情
4. 修复方式：删除不安全函数上的 `__init`/`__exit` 标记，或确保不通过持久结构体引用 __init 函数
**检查清单锚点**：编译 section mismatch 检查
**标签**：cross-project

### E040：OnePlus 4.19 内核 fsnotify 回调签名差异
**现象**：编译报 `incompatible function pointer types`，`susfs_sdcard_monitor.c` 中 `handle_event` 回调类型不匹配。
**根因**：OnePlus lineage-20 内核从 5.1+ 反向移植了 fsnotify API，`handle_event` 为 8 参数（含 `iter_info`），非标准的 9 参数（含两个 mark 指针）。
**教训**：1. OnePlus 内核非标准 4.19，API 签名以实际头文件为准 2. 移植前检查目标内核 `fsnotify_backend.h` 中 `struct fsnotify_ops`
**检查清单锚点**：目标内核 API 签名验证
**标签**：cross-project

### E041：`track_throne()` 包名匹配在 `prune_only` 之前执行
**现象**：每次重装 APK 后，KSU 管理器 App 显示"不支持/未集成"，需要手动 `ksud debug set-manager`
**根因**：内置内核模式下 `track_throne()` 的 `prune_only` 检查跳过管理器搜索。`on_boot_completed()` 传入 `prune_only=true`，管理器搜索代码在检查之后，开机后从不执行
**教训**：
1. 任何需要在 `prune_only=true` 路径下执行的逻辑必须放在 `prune_only` 检查之前
2. `uid_list`（包名↔UID 映射）在检查前已完整解析，可直接用于包名匹配
3. 包名匹配不可走 VFS（SUSFS 会隐藏路径），应直接遍历内存中的 `uid_list`
4. 重装后 UID 变化时，需同时检查 `!ksu_is_manager_appid_valid()` 和 `ksu_get_manager_appid() != uid`
**检查清单锚点**：「包名匹配在 `prune_only` 之前」+「`KSU_MANAGER_PACKAGE` 编译时定义」
**标签**：cross-project

### E042：`boot_complete_lock` 阻止 `on_boot_completed` 重复触发
**现象**：重装 APK 后 UID 变化，手动调用 `ksud boot-completed` 无效
**根因**：`dispatch.c` 中 `static bool boot_complete_lock` 确保 `on_boot_completed()` 只执行一次，重装后需再次触发自动注册但被锁阻止
**教训**：`track_throne()`、`avc_spoof_late_init()`、`selinux_hide_drop_backup_if_unused()` 均幂等，不需要锁保护
**检查清单锚点**：「`boot_complete_lock` 已移除」
**标签**：cross-project

### E043：YAML 内嵌 heredoc 的缩进冲突
**现象**：CI 构建失败：`Invalid workflow file: YAML syntax error on line 116`
**根因**：YAML `|` block 中使用 shell heredoc，内容缩进与 YAML 块不一致
**教训**：YAML `|` 块内全部内容必须保持一致的缩进级别。内嵌 heredoc 改用 `printf` 或外部 Python 脚本
**检查清单锚点**：「避免 YAML 内嵌 heredoc」
**标签**：cross-project

### E044：`setenforce` 在管理器中因 SELinux 域错误失败
**现象**：App 设置中切换 SELinux 模式后提示"设置SELinux模式失败: 0"
**根因**：`withNewRootShell` 创建的 shell 继承 App 的 SELinux 上下文（`untrusted_app`），没有 `SECURITY__SETENFORCE` 权限
**教训**：默认 root shell（`ShellUtils.fastCmdResult`）在 libsu 初始化时已建立，权限更可靠
**检查清单锚点**：「SELinux 切换使用默认 root shell」
**标签**：cross-project

### E045：dmesg 泄漏：`"KernelSU: "` 前缀 + 大量 `pr_info`/`pr_warn` 调用
**现象**：`dmesg` 中大量 `"KernelSU: "` 前缀泄漏内核修改。`pr_info`/`pr_warn` 泄漏操作详情
**根因**：`klog.h` 定义 `pr_fmt` 为 `"KernelSU: " fmt`。33 个 `.c` 文件共 491 处 `pr_*` 调用，仅 7 处受保护
**教训**：生产构建应将 `pr_info`/`pr_warn` 转为 `pr_debug`；`klog.h` 移除 `"KernelSU: "` 前缀
**检查清单锚点**：「`klog.h` 移除 `KernelSU:` 前缀」+「`pr_info`/`pr_warn`→`pr_debug`」
**标签**：cross-project

### E046：`PTE_MASK` 在 arm64 4.19 未定义
**现象**：CI 编译错误：`../drivers/kernelsu/feature/selinux_hide.c:184:26: error: use of undeclared identifier 'PTE_MASK'; did you mean 'PER_MASK'?`
**根因**：`PTE_MASK` 是 x86 体系结构宏，arm64 上不存在。fixmap ro_write 实现中 `phys_from_virt()` 函数在提取 PTE 物理地址时误用了它
**教训**：arm64 4.19 提取 PTE 中的物理地址应使用 `PHYS_MASK & PAGE_MASK`
**检查清单锚点**：「`PHYS_MASK & PAGE_MASK` 替代 `PTE_MASK`」

### E047：`core/init.c` 对 `ksu_selinux_hide_init` 三重调用导致重复注册
**现象**：dmesg 中 3 次 `"selinux_hide: initialized"` 日志，无实际危害但冗余
**根因**：`core/init.c` 有 3 处调用 `ksu_selinux_hide_init()`（不同初始化路径），Linux 内核 `module_init` 只执行首次，但此模块非标准 LKM，`init.c` 中的手动调用在 3 个路径上各触发一次
**教训**：非标准 init 路径的函数必须加幂等守卫
**检查清单锚点**：「`ksu_selinux_hide_init` 重复注册守卫」
**标签**：cross-project

### E048：`ro_write` 传参错误导致 write_op[] 写入函数指令而非函数指针
**现象**：Hide SELinux (feature 4) ON → 杀App重开 → 必崩。崩溃点 `selinux_transaction_write+0x5c` 通过 `write_op[ino]()` 间接调用时跳转到用户态地址 `0xbf5a9bd7bfd`。
**根因**：`ro_write(dst, &my_write_context, 8)` 中 `&my_write_context` 是函数入口地址。`memcpy(dst, &my_write_context, 8)` 从函数入口拷贝 8 字节 = 函数首条指令机器码（如 `0x910003fda9bf7bfd`），不是函数指针值。结果 `write_op[]` slot 存储的是垃圾指令地址。
**教训**：`ro_write` 写入函数指针时必须通过临时变量中转：`tmp = my_func; ro_write(dst, &tmp, sizeof(tmp))`。不能直接用 `&func_name` 作为 src。
**检查清单锚点**：「`ro_write` 传参用临时变量中转」

### E048：seccomp_cache.c 结构体不匹配导致堆溢出崩溃
**现象**：打开 Hide SELinux 后杀 App 重开必崩，PC alignment exception，`lr: selinux_transaction_write+0x5c/0x94`
**根因**：`seccomp_cache.c` 本地定义 `struct seccomp_filter` 含 `cache` 位图（>24 字节），但内核 4.19 实际 struct 仅 24 字节（`usage/log/prev/prog`）。`ksu_seccomp_allow_cache(current->seccomp.filter, __NR_reboot)` 通过 `set_bit()` 访问 `filter->cache.allow_native` 越界写堆 → 破坏相邻内核对象 → 后续 `write_op[ino]()` 拿到垃圾函数指针 → PC 对齐异常
**教训**：< 6.1 内核的 `struct seccomp_filter` 无 `cache` 字段，必须用版本守卫避免越界访问。统一做法：函数体用 `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)` 包裹
**检查清单锚点**：「`seccomp_cache.c` 版本守卫」
**标签**：cross-project

### E049：KPM 文件注入 KSUN 后 include 路径不匹配（policy/manager/infra 相对路径）

**现象**：编译报 `fatal error: 'policy/allowlist.h' file not found`，`drivers/kernelsu/kpm/compact.c` 找不到 include 文件。KPM IOCTL 代码未编译。

**根因**：SukiSU-Ultra 的 `kernel/kpm/compact.c` 使用 `#include "policy/allowlist.h"`，在其原生目录结构中 `kernel/` 是顶层，`kernel/policy/` 与其兄弟。但在 KSUN 树中，文件通过 `inject-kpm-subsystem.py` 注入到 `drivers/kernelsu/kpm/`，而 `policy/allowlist.h` 在 `drivers/kernelsu/policy/`。GCC 的 `#include "..."` 先搜索源文件所在目录（`kpm/`），找不到才搜 `-I` 路径。即使 KSUN Kbuild 有 `-I$(src)`，`#include "policy/..."` 也无法从 `kpm/` 解析到 `../policy/`。

**教训**：
1. 从 SukiSU-Ultra 复制 KPM 文件时，`compact.c` 和 `kpm.h` 的本地 `#include "xxx/"` 路径不能直接使用
2. 需要修正为 `../` 前缀才能从 `drivers/kernelsu/kpm/` 回到 `drivers/kernelsu/` 包含兄弟目录
3. `inject-kpm-subsystem.py` 的 `inject_kpm_files()` 必须在复制时做路径修正
4. 三个需要修正的文件：
   - `kpm.h`：`"uapi/supercall.h"` → `"../uapi/supercall.h"`
   - `compact.c`：`"infra/symbol_resolver.h"` → `"../infra/symbol_resolver.h"`
   - `compact.c`：`"policy/allowlist.h"` → `"../policy/allowlist.h"`
   - `compact.c`：`"manager/manager_identity.h"` → `"../manager/manager_identity.h"`
5. 此问题同样适用于从 SukiSU-Ultra 复制任何子目录文件到 KSUN 的 `drivers/kernelsu/` 下

**检查清单锚点**：KPM include 路径在 inject 脚本中修正

**标签**：cross-project
