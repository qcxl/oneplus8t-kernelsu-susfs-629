# porting-review — 内核功能移植审查流程

在开始任何移植工作前加载本 skill，自动引导完成源码阅读、全链路追踪、边界验证、提交前检查全流程。

## 使用场景

- 开始新功能移植（SUSFS、Magisk、KPM 等）
- 修复编译失败后的复盘
- 提交前的最终审查

## 启动

```bash
echo "当前项目上下文:"
head -30 TEST_PROCEDURE.md 2>/dev/null | grep -A5 '^### 项目标识' || echo "（未找到项目上下文，请先填写 TEST_PROCEDURE.md 第 II 部分）"
echo ""
echo "最新错误经验:"
grep "^### E00" ERRORS.md 2>/dev/null | tail -3 || echo "（ERRORS.md 不存在或为空）"
echo ""
echo "当前移植进度:"
grep 'Batch\|✅\|🚧\|❌' TEST_PROCEDURE.md 2>/dev/null | tail -5 || echo "（未找到进度信息）"
```

---

## 阶段 1：移植前检查

### 1a. 源码阅读确认

按以下顺序完成阅读，每项完成后确认：

1. **头文件常量**：读取 `susfs_def.h`，记录所有 `CMD_*`、`INODE_STATE_*`、`AS_FLAGS_*`、`SUSFS_*_SIZE`
2. **结构体定义**：读取 `susfs.h`，基线版本 vs 目标版本逐字段对比
3. **函数声明**：逐函数对比签名变化（返回类型、参数类型）
4. **函数实现**：读取目标版本函数体，标注所有外部依赖
5. **补丁文件**：读取 `50_add` 补丁，找到 VFS 挂钩精确位置

⚠️ 关键风险：本地下载的镜像版本（hypermezo4 v1.5.9）可能与 CI 使用的 gitlab 版本（v1.5.5）存在 struct 差异

### 1b. 依赖追踪

对每个新功能，逐项确认：
- 全局变量：在 KSUN 源码中搜索 `extern`
- 锁机制：`spin_lock`/`mutex`/`SRCU`/`RCU` 在 kernel 4.19 可用性
- 外部函数：`kern_path`、`kzalloc`、`override_creds` 等
- 宏：`WRITE_ONCE`、`set_bit`、`hash_for_each_possible_rcu` 等

### 1c. 全链路追踪

追踪代码路径：用户态命令 → syscall → dispatch 入口 → 功能函数 → VFS 钩子。

确认 dispatch 模板引用的每个 `CMD_*` 常量在 `susfs_def.h` 中都有 `#define`。

---

## 阶段 2：代码实现后的审计

### 2a. 注入脚本检查
- [ ] `python3 -c "import py_compile; py_compile.compile('scripts/inject-xxx.py', doraise=True)"`
- [ ] `grep -n '/Users/\|/home/' scripts/inject-*.py` 无本地硬编码路径
- [ ] 缩进一致（Python 4空格，C 代码 `\t`）
- [ ] 本地定义的结构体不引用外部类型
- [ ] insert_before_line/replace_in_file 返回值被检查

### 2b. 一致性检查
- [ ] dispatch 条目（IOCTL + reboot 两处）都添加了
- [ ] `ksu.config` 和 GHA workflow 的 Kconfig 注册同步添加
- [ ] 去重保护（幂等性）：第二遍运行不破坏代码
- [ ] 桩函数 `susfs_stubs.c` 同步更新

### 2c. 运行提交前检查
```bash
bash scripts/pre-flight-check.sh
```
必须 0 阻断才能提交。

---

## 阶段 3：修复后复盘

每次修复编译失败后：

1. 在 `ERRORS.md` 新增 `### E00N：` 条目
2. 记录四项：**现象** / **根因** / **教训** / **检查清单锚点**
3. 如果教训对应新的检查类型，更新 `TEST_PROCEDURE.md` 清单
4. 如果适用于自动化，更新 `pre-flight-check.sh`

---

## 阶段 4：刷机验证

参考 [FLASH_PROCEDURE.md](../../FLASH_PROCEDURE.md) 按步骤操作。必须保存现场日志。

---

## 原则

- **一次只移植一个函数**。追踪其所有依赖，确认基线版本中对应的部分，再读下一个
- **不武断删除功能**。对每个依赖做完整可行性调研，搜索范围覆盖全部源码文件
- **所有 bug 必须有根因分析**才能提交修复。提交前运行 pre-flight-check
