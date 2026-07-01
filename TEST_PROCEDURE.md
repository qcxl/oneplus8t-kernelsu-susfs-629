# 测试流程

---

## ⚠️ 移植前强制检查清单（每次移植必须逐项完成，不得跳过）

### 1. 源码阅读
- [ ] 读完 v1.5.5 对应功能的全部实现代码（包括辅助函数、宏定义）
- [ ] 读完 v2.2.0 对应功能的全部实现代码
- [ ] 读完 VFS 层调用点的上下文（如 fs/stat.c、fs/proc/task_mmu.c 中相关函数）
- [ ] 读完涉及的结构体定义、枚举常量、Kconfig 依赖链

### 2. 全链路追踪
- [ ] 追踪每条代码路径：用户态命令 → syscall → dispatch 入口 → SUSFS 函数 → VFS 钩子
- [ ] 确认头文件 `#include` 链完整（每个用到的宏/结构体在哪个头文件定义）
- [ ] 确认函数签名匹配（v1.5.5 是 `int func(struct xxx* __user)`，v2.2.0 是 `void func(void __user **)`）
- [ ] **确认注入标记在目标文件中确实存在**（`/* susfs_init */`、锚点行、`#endif` 等）
- [ ] **注入脚本必须检查插入是否成功，失败必须返回 False 终止构建**（切勿静默跳过）
- [ ] **功能可行性调研**：对每个新功能，逐项检查所有依赖在目标环境（`v1.5.5 + KSUN-legacy + kernel 4.19`）是否可用。依赖类型包括：全局变量、锁机制（spinlock/mutex/SRCU）、外部函数、内核头文件宏。搜索范围覆盖项目全部源码文件，不限预判路径。确认不可用后才可记录原因并标记暂缓

### 3. 边界条件和副作用验证
- [ ] 符号冲突检查：新函数名/全局变量名是否与 KSU 或其他模块重复
- [ ] 内核版本兼容性检查：`WRITE_ONCE`、`SRCU`、`kzalloc`、`set_bit` 等在 kernel 4.19 是否可用
- [ ] 多次执行去重保护（幂等性）：同一脚本运行两次不应破坏代码
- [ ] `#ifdef` 条件完备性：新增 Kconfig 选项 = n 时，相关代码应完全跳过
- [ ] `__user` 注解正确性：所有用户态指针传递路径有 `__user` 标注
- [ ] 内存安全：`copy_from_user`/`copy_to_user` 返回值被检查，`kmalloc` 返回值被检查
- [ ] **脚本注入点验证：插入的结构体和函数声明应放在一起（避免半插入状态——声明在但定义不在）**
- [ ] **缩进一致性：同一个 inject 脚本内不得混用空格和 tab。Python 字符串模板中 C 代码用 `\t` 转义，Python 本身用 4 空格缩进。替换 edit 后检查上下文缩进层级一致**

### 3b. ⚠️ 常见失败模式（从历史 bug 总结，逐条对照）
- [ ] 🔴 **静默跳过**：注入脚本的锚点 `if xxx in line` 不匹配时，是否返回 False 而不是无声继续？
- [ ] 🔴 **文件版本差异**：本地读的版本可能 ≠ GHA 构建用的版本。不要假设本地文件等价于 gitlab 源文件
- [ ] 🔴 **"前向声明"错误**：编译报 `incomplete type / forward declaration` = 结构体定义没插进去。原因通常是锚点不匹配或插入点在 `#ifdef` 块外
- [ ] 🔴 **替换丢失 `#define`**：字符串替换时，确保替换范围包含完整行（`#define FOO 1` 而非只替换 `FOO`）
- [ ] 🔴 **双 `#define`**：替换目标内容本身以 `#define` 开头时，目标字符串也需以 `#define` 匹配
- [ ] 🔴 **GHA 步骤顺序**：inject 脚本执行时，被修改的文件必须已存在。确认步骤顺序且不被后续步骤覆盖

### 4. 移植后全面审计（代码写完后、提交前）
- [ ] **Python 语法检查：`python3 -c \"import py_compile; py_compile.compile('scripts/xxx.py', doraise=True)\"`，每个修改过的 inject 脚本都要检查**
- [ ] 逐行审查每个改动文件，确认无笔误（变量名、函数名、拼写）
- [ ] 结构体布局与 v2.2.0 一致，`err` 字段在末尾
- [ ] dispatch 条目（IOCTL + reboot 两处）都添加了
- [ ] **Kconfig 一致性：新增 `CONFIG_*` 时，`ksu.config` 和 GHA workflow 的 Kconfig 注册同步添加**
- [ ] 桩函数（susfs_stubs.c）更新/删除同步
- [ ] 去重保护代码与注入逻辑一致（避免半插入状态）
- [ ] **路径检查：`grep -n '/Users/\|/home/' scripts/*.py` 确保无本地硬编码绝对路径**

### 5. 提交规范
- [ ] **提交前运行 `bash scripts/pre-flight-check.sh`，全部通过才允许提交**
- [ ] 提交信息格式：`feat: batchN v2.2.0 port - 功能名`
- [ ] 提交信息包含移植依据、关键决策说明
- [ ] 只提交移植相关文件，不包括临时文件、备份文件

---

## 🔄 事后复盘：错误经验提炼（每次修复后立即执行）

每次解决一个 bug 后，必须在 [ERRORS.md](ERRORS.md) 新增条目。步骤如下：

### 步骤
1. 在 `ERRORS.md` 新开一个 `### E00N：` 条目
2. 记录四项内容：
   - **现象**：编译/运行时观察到什么
   - **根因**：为什么发生
   - **教训**：如何避免（具体操作，而非笼统建议）
   - **检查清单锚点**：关联到本文第 2/3/4 节具体哪条检查项
3. 如果新教训无法对应到现有检查项，则在对应节新增一条检查项
4. 如果适用于自动化检查，更新 `scripts/pre-flight-check.sh`

### 判断标准
以下情况必须记录：
- 🔴 编译失败（任何原因）
- 🔴 运行时 crash（panic/Oops/重启）
- 🟡 功能不符合预期（命令输出错误、特征不起作用）
- 🟡 审计发现的结构体/签名不匹配
- 🟢 值得记录的心得（新的 kernel 版本兼容性发现、工具用法技巧）

---


---

## 🔴 刷机前强制环境检查（跳过任何一项都不得刷机）

### 1. 电脑端工具链检查
```bash
# adb 可用
adb --version
# fastboot 可用
fastboot --version
# gh CLI 可用
gh --version
```

### 2. 手机连接状态检查
```bash
# 确认设备已连接且 adb 可达
adb get-state
# 预期: device
# 如果返回 "unknown" 或 "offline": 重新插拔 USB 或重启 adb 服务

# 确认 adb root 权限正常
adb root
adb shell id
# 预期: uid=0(root)
# 如果无法 root: 手机可能需要解锁或授权

# 确认手机当前处于系统桌面（不是 fastboot/recovery）
adb shell dumpsys window | grep mCurrentFocus | grep -i 'launcher\|desktop\|SystemUI'
# 确认设备不是 fastboot 模式
fastboot devices 2>&1 | grep -v '^$' && echo "WARNING: 设备在 fastboot 模式！adb 不可用"
```

### 3. 刷机包完整性检查
```bash
# 文件存在且大小正确（OnePlus 8T boot 分区 = 96MB = 100663296 字节）
BOOT_IMG="<path>/ksu-debug-boot.img"
ls -lh "$BOOT_IMG"
SIZE=$(stat -f%z "$BOOT_IMG" 2>/dev/null || stat -c%s "$BOOT_IMG" 2>/dev/null)
if [ "$SIZE" != "100663296" ]; then
  echo "ERROR: boot.img 大小异常！预期 96MB 实际 $(($SIZE/1024/1024))MB"
  exit 1
fi

# ANDROID! 魔数校验
MAGIC=$(xxd -l 8 "$BOOT_IMG" 2>/dev/null | head -1 | grep 'ANDROID' && echo "OK" || echo "FAIL")
if [ "$MAGIC" != "OK" ]; then
  hexdump -C "$BOOT_IMG" | head -1 | grep 'ANDROID' > /dev/null && echo "ANDROID! 魔数: OK" || echo "ERROR: 不是有效的 Android boot.img！"
fi

# SHA256 校验（与 GHA 构建产物对比）
sha256sum "$BOOT_IMG" > /tmp/flash-刷机包.sha256
echo "刷机包 SHA256: $(cat /tmp/flash-刷机包.sha256)"
```

### 4. 设备分区状态检查
```bash
# 查看当前启动槽位
adb shell getprop ro.boot.slot_suffix
# 预期: _a 或 _b

# 确认 boot 分区存在且大小正常
adb shell ls -la /dev/block/by-name/boot_a /dev/block/by-name/boot_b 2>&1

# 记录当前启动槽位（刷机后用于对比）
adb shell getprop ro.boot.slot_suffix > /tmp/flash-刷前槽位.log

# 记录当前已安装的 ksud 版本
adb shell /data/adb/ksu/ksud debug version > /tmp/flash-刷前ksud版本.log 2>&1
```


```bash
# 1. 清旧日志
rm -f /tmp/flash-*.log /tmp/dmesg-*.log /tmp/logcat-*.log

# 2. 保存当前系统状态（如果设备还活着）
STATE=$(adb get-state 2>/dev/null)
echo "state=$STATE" > /tmp/flash-刷前状态.log
adb shell uptime >> /tmp/flash-刷前状态.log 2>&1
adb shell dmesg | grep 'Power-off reason\|Power-on reason' > /tmp/flash-刷前pmic.log 2>&1
adb shell dmesg | tail -20 > /tmp/flash-刷前dmesg-tail.log 2>&1

# 3. 启动实时监控（刷机后如果设备能启动，这些日志会被持续写入）
adb shell dmesg -w > /tmp/dmesg-现场.log &
DMESG_PID=$!
adb logcat -b all > /tmp/logcat-现场.log &
LOGCAT_PID=$!
echo "监控 PID: dmesg=$DMESG_PID logcat=$LOGCAT_PID" >> /tmp/flash-刷前状态.log
```

## 刷机

```bash
adb reboot bootloader
sleep 8
fastboot boot <path>/ksu-debug-boot.img
```

如果 `fastboot boot` 卡住或失败：
```bash
# 保存 fastboot 输出
fastboot boot ksu-debug-boot.img 2>&1 | tee /tmp/flash-fastboot-error.log
# 尝试重启到 bootloader 重试
fastboot reboot-bootloader
```

## 刷机后：系统性验证清单

### 1. 基础连通性
- [ ] 设备在 60 秒内通过 adb 连接
- [ ] `adb root` 成功
- [ ] 设备进入系统桌面

### 2. 稳定性基线监控
- [ ] dmesg 无 `panic|BUG|Oops|Call Trace`
- [ ] dmesg 无 `sched: Unexpected reschedule of offline CPU`
- [ ] PMIC 关机原因 = `PS_HOLD`（正常），非 `HARD_RESET`（异常重启）
- [ ] 持续运行 5 分钟不自动重启
- [ ] 持续运行 10 分钟再次检查 PMIC 关机原因

### 3. SUSFS 命令验证（ksud）
```bash
adb shell /data/adb/ksu/ksud susfs version     
# 预期: v1.5.5
adb shell /data/adb/ksu/ksud susfs variant     
# 预期: NON-GKI
adb shell /data/adb/ksu/ksud susfs support      
# 预期: Supported
adb shell /data/adb/ksu/ksud susfs features     
# 预期: 列出已启用的功能名（文本格式）
```

### 4. 本次移植功能专项验证（Batch 1: avc_log + enable_log）

#### 4a. 内核符号验证
```bash
# 检查新函数是否编译进内核
adb shell cat /proc/kallsyms | grep 'susfs_set_avc_log_spoofing'
# 预期: 显示符号地址

adb shell cat /proc/kallsyms | grep 'susfs_enable_log'
# 预期: 显示符号地址

adb shell cat /proc/kallsyms | grep 'susfs_is_avc_log_spoofing_enabled'
# 预期: 显示符号地址
```

#### 4b. IOCTL 分发验证（KSUN dispatch 注册）
```bash
adb shell dmesg | grep 'SUSFS'
# 预期包含: SUSFS = 0x00000055    ← dispatch 表中有 SUSFS 条目

adb shell dmesg | grep 'susfs: ioctl\|susfs: reboot'
```

#### 4c. AVC Log Spoofing 功能验证
```bash
# 检查是否加载到了 avc_spoof feature
adb shell /data/adb/ksu/ksud feature list | grep 'avc'
# 预期: avc_spoof (ID=10003)  ENABLED

# 检查内核日志中是否有 avc_spoof 相关输出
adb shell dmesg | grep -i 'avc_spoof'
```

#### 4d. enable_log v2.2.0 协议验证
```bash
# 发送 CMD_SUSFS_ENABLE_LOG (0x555a0) 并检查 err=0 响应
# 暂用直接 strace 验证 syscall 返回值
adb shell strace -e reboot /data/adb/ksu/ksud debug version 2>&1 | head -5
```

### 5. 本次移植功能专项验证（依批次添加）

#### Batch 1: avc_log + enable_log（已通过）
```bash
# 内核符号
adb shell cat /proc/kallsyms | grep 'susfs_set_avc_log_spoofing\|susfs_enable_log'
# avc_spoof feature 注册
adb shell /data/adb/ksu/ksud feature list | grep 'avc'
```

#### Batch 2: hide_mnts + fillattr + map_vma + path_loop
```bash
# hide_sus_mnts 符号
adb shell cat /proc/kallsyms | grep 'susfs_set_hide_sus_mnts\|susfs_hide_sus_mnts_for_all_procs'
# fillattr_spoofer 符号
adb shell cat /proc/kallsyms | grep 'susfs_generic_fillattr_spoofer\|susfs_show_map_vma_spoofer'
# path_loop 符号
adb shell cat /proc/kallsyms | grep 'susfs_add_sus_path_loop\|susfs_extra_works'
# VFS 钩子已更新
adb shell dmesg | grep 'stat.c\|task_mmu' || echo "VFS 钩子无直接日志，检查 kallsyms 确认编译"
```

### 6. KSU 内核功能验证
```bash
adb shell /data/adb/ksu/ksud debug version
# 预期: 33133

adb shell demosg | grep 'KernelSU'
# 预期: 显示 KSU IOCTL 命令表、LSM hooks 初始化等
```

### 6. 异常情况处理

#### 6a. 刷机后设备无法进入系统
```bash
# 1. 等 2 分钟让设备充分启动
# 2. 检查 fastboot 是否还能连接
fastboot devices

# 3. 如果可以，刷回上一个已知正常的 boot.img
fastboot boot /tmp/kernel-test-3/ksu-debug-boot.img  # 上一个版本

# 4. 分析现场日志
grep -i 'panic\|error\|fail' /tmp/dmesg-现场.log 2>/dev/null | tail -20
grep -i 'panic\|error\|fail' /tmp/logcat-现场.log 2>/dev/null | tail -20
```

#### 6b. SUSFS 命令失败
```bash
# 1. 检查 syscall 层级
adb shell strace -e reboot /data/adb/ksu/ksud susfs version 2>&1
# 看返回值和 errno

# 2. 检查内核侧是否收到命令
adb shell dmesg | grep 'susfs:'

# 3. 检查 ksud 版本和通信通道
adb shell /data/adb/ksu/ksud debug version
adb shell ls -la /data/adb/ksu/ksud
```

#### 6c. 编译失败
```bash
# 1. 获取构建日志
gh run view --log 2>&1 | tee /tmp/build-失败.log

# 2. 定位错误类型和位置
grep -n 'error:\|Error:\|FAILED\|fatal' /tmp/build-失败.log | head -20

# 3. 如果是 Python 脚本错误（IndentationError/SyntaxError/ImportError）
grep -B5 'IndentationError\|SyntaxError\|FileNotFoundError\|ImportError' /tmp/build-失败.log

# 4. 如果是 C 编译错误
grep -B2 'error:' /tmp/build-失败.log | grep -v '^\-\-$' | head -30
# 查找具体文件和行号
grep '\.c\|\.h' /tmp/build-失败.log | grep 'error:' | head -10

# 5. 如果是链接错误（undefined reference）
grep -B1 'undefined reference' /tmp/build-失败.log | head -10

# 6. 如果是 Kconfig/配置错误
grep 'config\|\.config\|merge_config' /tmp/build-失败.log | grep -i 'error\|fail\|warn'

# 7. 定位到具体代码行后，修复并重新提交。记录经验到 ERRORS.md
```
