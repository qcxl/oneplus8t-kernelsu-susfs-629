# porting-review — 内核功能移植审查流程

在开始任何移植工作前加载本 skill，自动引导完成全流程。

---

## 启动

```bash
echo "=== 项目上下文 ==="
grep -A5 '项目标识\|^### 项目' TEST_PROCEDURE.md 2>/dev/null || echo "（无）"
echo ""
echo "=== 最新错误经验 ==="
grep "^### E00" ERRORS.md 2>/dev/null | tail -3
echo ""
echo "=== 移植进度 ==="
grep 'Batch\|✅\|🚧\|❌' TEST_PROCEDURE.md 2>/dev/null | tail -5
echo ""
echo "=== 当前目录 ==="
ls -la .claude/skills/porting-review/
```

---

## 阶段 1：移植前强制检查

### 1a. 源码阅读（规范化顺序）

**阅读顺序**：头文件 → 函数声明 → 结构体定义 → 函数实现 → VFS 调用点 → 补丁文件

- 1a.1 先确认源文件版本：gitlab 原始版 vs GitHub 镜像版可能不同。**以 CI 实际使用的源为准**
- 1a.2 完整读取 `susfs_def.h`，记录所有 `CMD_*`、`INODE_STATE_*`、`AS_FLAGS_*`、`SUSFS_*_SIZE` 常量
- 1a.3 完整读取 `susfs.h`，**基线版本和目标版本逐字段对比结构体**，标记增删改字段
- 1a.4 逐函数对比签名变化（返回类型 `int`→`void`？参数 `单指针`→`双指针`？`ino`→`inode*`？）
- 1a.5 读取目标版本函数体，标注每个外部依赖（调用了哪些宏、函数、全局变量）
- 1a.6 读取 `50_add` 补丁，找到 VFS 挂钩的精确插入位置

### 1b. 经验陷阱（从历史错误总结）

| # | 风险 | 案例 |
|---|------|------|
| 1 | **本地文件 ≠ CI 源文件**。GitHub 镜像可能比 gitlab 原始版更新 | E002/E005/E009 |
| 2 | **结构体必须逐字段对比**。v1.5.5 的 `open_redirect_hlist` 只有 4 字段，v2.2.0 有 9 字段 | Batch 3 |
| 3 | **函数签名变化必须映射**。`int func(xxx*)` → `void func(void**)` 涉及全部参数传递方式变化 | E001-E003 |
| 4 | **VFS 挂钩点从 50_add 补丁中找**。不在目标版本代码中猜测 | Batch 2 |
| 5 | **不要假设"这个结构体肯定有 err 字段"**。v1.5.5 所有 struct 都没有 err 字段 | Batch 1 |
| 6 | **不要假设"这个函数肯定存在"**。如 `ksu_cred` 在 KSUN 中存在但路径不同 | E006 |

### 1c. 依赖追踪（每个新功能独立完成）

- [ ] **全局变量**：列出所有 `extern` 变量，**搜索范围覆盖项目全部源码文件**（KSUN、内核头文件、其他模块），不限于预判路径
- [ ] **锁机制**：标注 `spin_lock`/`mutex`/`SRCU`/`RCU`，确认 kernel 4.19 支持且头文件已包含
- [ ] **外部函数**：`kern_path`、`kzalloc`、`override_creds`、`get_fuse_inode` 等逐一确认可用
- [ ] **宏/内联函数**：`WRITE_ONCE`、`set_bit`、`hash_for_each_possible_rcu` 等在目标内核版本中定义

### 1d. 全链路追踪

- [ ] 追踪代码路径：用户态命令 → syscall → dispatch 入口 → 功能函数 → VFS 钩子
- [ ] 确认头文件 `#include` 链完整（每个宏/结构体在哪个头文件定义）
- [ ] 确认函数签名是否变化
- [ ] **确认注入标记在目标文件中确实存在**（`/* susfs_init */`、锚点行等）
- [ ] **注入脚本必须检查插入是否成功**，失败返回 False 终止构建（勿静默跳过）
- [ ] **功能可行性调研**：每个新功能的全部依赖在目标环境是否可用。确认不可用才标记暂缓，不可武断删除

### 1e. 边界条件和副作用验证

- [ ] 符号冲突：新函数名/全局变量名是否与其他模块重复
- [ ] 内核版本兼容性：所用内核 API 在目标版本可用
- [ ] 幂等性：同一脚本运行两次不破坏代码
- [ ] `#ifdef` 完备：新增 Kconfig=n 时相关代码应完全跳过
- [ ] `__user` 注解：所有用户态指针传递路径有 `__user` 标注
- [ ] 内存安全：`copy_from_user/to_user` 返回值被检查，`kmalloc` 返回值被检查
- [ ] **结构体和函数声明一起插入**（避免半状态）
- [ ] **缩进一致**：Python 4 空格，C 代码 `\t`，替换后检查上下文缩进层级
- [ ] **局部结构体自包含**：不得引用外部类型作为字段，必须平铺展开

### 1f. 常见失败模式逐条对照

- [ ] 🔴 **静默跳过**：锚点不匹配时返回 False？不是无声继续？
- [ ] 🔴 **文件版本差异**：本地 ≠ CI，不要假设本地等价于上游源文件
- [ ] 🔴 **前向声明错误**：`incomplete type` = 结构体定义没插进去。原因：锚点不匹配或插入点在 `#ifdef` 块外
- [ ] 🔴 **替换丢失 `#define`**：替换完整行（`#define FOO 1`），不只替换 `FOO`
- [ ] 🔴 **双 `#define`**：替换目标以 `#define` 开头时，目标字符串也以 `#define` 匹配。替换范围必须包含完整行，否则变 `#define #define XXX`
- [ ] 🔴 **CI 步骤顺序**：inject 脚本执行时被修改的文件必须已存在

---

## 阶段 2：代码实现后的全面审计

### 2a. 注入脚本检查（阻断项）
- [ ] `python3 -c "import py_compile; py_compile.compile('scripts/inject-xxx.py', doraise=True)"`（每个修改的脚本）
- [ ] `grep -n '/Users/\|/home/' scripts/*.py` 无本地硬编码绝对路径
- [ ] 缩进一致
- [ ] 本地结构体不引用外部类型
- [ ] `insert_before_line`/`replace_in_file` 返回值被检查

### 2b. 一致性检查
- [ ] dispatch 条目（IOCTL + reboot 两处）都添加了
- [ ] **dispatch 模板引用的每个 `CMD_*` 常量，在 `susfs_def.h` 中都有 `#define` 定义**（否则编译报 `use of undeclared identifier`，如 E010）
- [ ] `ksu.config` 和 GHA workflow 的 Kconfig 注册同步添加
- [ ] 去重保护（幂等性）
- [ ] 桩函数 `susfs_stubs.c` 同步更新

### 2c. 运行提交前检查
```bash
bash scripts/pre-flight-check.sh
```
**必须 0 阻断才能提交。** 如果失败，返回阶段 1 定位问题。

### 2d. 提交规范
- [ ] 提交前运行 `pre-flight-check.sh` ✅
- [ ] 提交信息格式：`feat: 项目名-版本 移植 - 功能说明`
- [ ] 注入脚本修改后，commit message 必须引用新的 E00N 编号
- [ ] 只提交移植相关文件，不包括临时文件/备份文件

---

## 阶段 3：修复后复盘（每次修复后立即执行）

每次解决一个 bug 后，**在提交前**执行以下步骤：

1. 在 `ERRORS.md` 新开 `### E00N：` 条目
2. 记录四项内容：
   - **现象**：编译/运行时观察到什么
   - **根因**：为什么发生
   - **教训**：如何避免（具体操作）
   - **检查清单锚点**：关联到本文阶段 1 的对应检查项
3. 如果教训对应新的检查类型，更新 `TEST_PROCEDURE.md` 清单
4. 如果适用于自动化，更新 `pre-flight-check.sh`

**判断标准（以下必须记录）：**
- 🔴 编译失败（任何原因）
- 🔴 运行时 crash（panic/Oops/重启）
- 🟡 功能不符合预期
- 🟡 审计发现的结构体/签名不匹配
- 🟢 值得记录的心得

---

## 阶段 4：刷机验证

### 4a. 刷机前强制检查

```bash
# 1. 工具链
adb --version && fastboot --version && gh --version

# 2. 手机状态
adb get-state        # 预期: device
adb root && adb shell id  # 预期: uid=0(root)

# 3. 刷机包完整性
BOOT_IMG="刷机包.img"
ls -lh "$BOOT_IMG"
hexdump -C "$BOOT_IMG" | head -1 | grep 'ANDROID' && echo "魔数 OK" || echo "ERROR"

# 4. 分区状态
adb shell getprop ro.boot.slot_suffix > /tmp/flash-刷前槽位.log
adb shell /data/adb/ksu/ksud debug version > /tmp/flash-刷前ksud版本.log

# 5. 基线保存 + 日志监控
rm -f /tmp/dmesg-*.log /tmp/logcat-*.log
adb shell dmesg | grep 'Power-off reason' > /tmp/flash-刷前pmic.log
adb shell dmesg -w > /tmp/dmesg-现场.log &
adb logcat -b all > /tmp/logcat-现场.log &
```

### 4b. 刷机
```bash
adb reboot bootloader && sleep 8 && fastboot boot <刷机包.img>
```

### 4c. 刷机后验证
- [ ] 60 秒内 adb 连接
- [ ] `adb root` 成功
- [ ] dmesg 无 `panic|BUG|Oops|Call Trace`
- [ ] PMIC 关机原因 = `PS_HOLD`（正常）
- [ ] 持续运行 5 分钟不自动重启
- [ ] `ksud susfs version/variant/support/features` 全部正常
- [ ] 新功能的符号在 kallsyms 中可见

### 4d. 异常处理
- **设备无法进入系统** → `fastboot boot <上一个已知正常的boot.img>`，分析 `/tmp/dmesg-现场.log`
- **SUSFS 命令失败** → `strace -e reboot /data/adb/ksu/ksud susfs version` 检查 syscall
- **编译失败** → `gh run view --log 2>&1 | grep -i 'error:'` 定位，修复后执行阶段 3

---

## 原则

1. **一次只移植一个函数**。追踪全部依赖后再读下一个
2. **不武断删除功能**。对每个依赖做完整可行性调研，搜索全部源码文件。确认不可用后才记录原因标记暂缓
3. **所有 bug 必须有根因分析才能提交修复**。修复后必须执行阶段 3 提炼经验
4. **提交前必须运行 `pre-flight-check.sh`**。0 阻断才能提交
