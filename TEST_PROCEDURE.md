# 测试流程与移植规范

> 本文档分为两层：
> - **第 I 部分：通用移植方法论**——适用于所有内核功能移植（SUSFS、Magisk、KPM 等）
> - **第 II 部分：项目上下文**——当前项目的特定参数，每次新项目替换此处即可

---

# 第 I 部分：通用移植方法论

## ⚠️ 移植前强制检查清单（每次移植必须逐项完成，不得跳过）

### 1. 源码阅读
- [ ] 读完**基线版本**对应功能的全部实现代码（包括辅助函数、宏定义）
- [ ] 读完**目标版本**对应功能的全部实现代码
- [ ] 读完 VFS 层调用点的上下文（如 stat.c、task_mmu.c 等被修改的文件）
- [ ] 读完涉及的结构体定义、枚举常量、Kconfig 依赖链

### 2. 全链路追踪
- [ ] 追踪每条代码路径：用户态命令 → syscall → dispatch 入口 → 功能函数 → VFS 钩子
- [ ] 确认头文件 `#include` 链完整（每个用到的宏/结构体在哪个头文件定义）
- [ ] 确认函数签名是否变化：基线版本签名 vs 目标版本签名
- [ ] **确认注入标记在目标文件中确实存在**（注释标记、锚点行、`#endif` 等）
- [ ] **注入脚本必须检查插入是否成功，失败必须返回 False 终止构建**（切勿静默跳过）
- [ ] **功能可行性调研**：对每个新功能，逐项检查所有依赖在目标环境是否可用。依赖类型包括：全局变量、锁机制、外部函数、内核头文件宏。搜索范围覆盖项目全部源码文件

### 3. 边界条件和副作用验证
- [ ] 符号冲突检查：新函数名/全局变量名是否与其他模块重复
- [ ] 内核版本兼容性检查：所用内核 API 在目标内核版本是否可用
- [ ] 多次执行去重保护（幂等性）：同一脚本运行两次不应破坏代码
- [ ] `#ifdef` 条件完备性：新增 Kconfig 选项 = n 时，相关代码应完全跳过
- [ ] `__user` 注解正确性：所有用户态指针传递路径有 `__user` 标注
- [ ] 内存安全：`copy_from_user`/`copy_to_user` 返回值被检查，`kmalloc` 返回值被检查
- [ ] **脚本注入点验证：插入的结构体和函数声明应放在一起（避免半插入状态）**
- [ ] **缩进一致性：同一个 inject 脚本内不得混用空格和 tab。Python 字符串模板中 C 代码用 `\t` 转义，Python 本身用 4 空格缩进。替换 edit 后检查上下文缩进层级一致**

### 3b. ⚠️ 常见失败模式（从历史 bug 总结，逐条对照）
- [ ] 🔴 **静默跳过**：注入脚本的锚点 `if xxx in line` 不匹配时，是否返回 False 而不是无声继续？
- [ ] 🔴 **文件版本差异**：本地读的版本可能 ≠ CI 构建用的版本。不要假设本地文件等价于上游源文件
- [ ] 🔴 **"前向声明"错误**：编译报 `incomplete type / forward declaration` = 结构体定义没插进去。原因通常是锚点不匹配或插入点在 `#ifdef` 块外
- [ ] 🔴 **替换丢失 `#define`**：字符串替换时，确保替换范围包含完整行（`#define FOO 1` 而非只替换 `FOO`）
- [ ] 🔴 **双 `#define`**：替换目标内容本身以 `#define` 开头时，目标字符串也需以 `#define` 匹配
- [ ] 🔴 **CI 步骤顺序**：inject 脚本执行时，被修改的文件必须已存在。确认步骤顺序且不被后续步骤覆盖

### 4. 移植后全面审计（代码写完后、提交前）
- [ ] **Python 语法检查：`python3 -c \"import py_compile; py_compile.compile('scripts/xxx.py', doraise=True)\"`，每个修改过的 inject 脚本都要检查**
- [ ] 逐行审查每个改动文件，确认无笔误（变量名、函数名、拼写）
- [ ] 结构体布局与目标版本一致（注意 `err` 字段、新加字段的 ABI 兼容性）
- [ ] dispatch/入口条目（IOCTL + reboot/其他通道）都添加了
- [ ] **Kconfig 一致性：新增 `CONFIG_*` 时，`kernel-patches/*.config` 和 CI workflow 的 Kconfig 注册同步添加**
- [ ] 桩函数/兼容性代码更新/删除同步
- [ ] 去重保护代码与注入逻辑一致（避免半插入状态）
- [ ] **路径检查：确保无本地硬编码绝对路径**

### 5. 提交规范
- [ ] **提交前运行 `bash scripts/pre-flight-check.sh`，全部通过才允许提交**
- [ ] 提交信息格式：`feat: 项目名-版本 移植 - 功能说明`
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
- 🟢 值得记录的心得（新的内核版本兼容性发现、工具用法技巧）

---

## 🔴 刷机前强制环境检查（跳过任何一项都不得刷机）

### 1. 电脑端工具链检查
```bash
adb --version
fastboot --version
gh --version
```

### 2. 手机连接状态检查
```bash
adb get-state                             # 预期: device
adb root && adb shell id                  # 预期: uid=0(root)
adb shell dumpsys window | grep mCurrentFocus | grep -i 'launcher\|desktop\|SystemUI'
fastboot devices 2>&1 | grep -v '^$' && echo "WARNING: 设备在 fastboot 模式"
```

### 3. 刷机包完整性检查
```bash
BOOT_IMG="<path>/刷机包.img"
ls -lh "$BOOT_IMG"
SIZE=$(stat -f%z "$BOOT_IMG" 2>/dev/null || stat -c%s "$BOOT_IMG" 2>/dev/null)
# 检查 boot.img 魔数
hexdump -C "$BOOT_IMG" | head -1 | grep 'ANDROID' > /dev/null && echo "ANDROID! 魔数: OK" || echo "ERROR: 不是有效的 Android boot.img！"
sha256sum "$BOOT_IMG" > /tmp/flash-刷机包.sha256
```

### 4. 设备分区状态检查
```bash
adb shell getprop ro.boot.slot_suffix > /tmp/flash-刷前槽位.log
adb shell ls -la /dev/block/by-name/boot  # 确认 boot 分区存在
adb shell /data/adb/ksu/ksud debug version > /tmp/flash-刷前ksud版本.log 2>&1
```

### 5. 基线保存 + 日志监控启动
```bash
# 清旧日志
rm -f /tmp/flash-*.log /tmp/dmesg-*.log /tmp/logcat-*.log
# 保存刷前状态
adb shell uptime > /tmp/flash-刷前状态.log
adb shell dmesg | grep 'Power-off reason' > /tmp/flash-刷前pmic.log
# 启动实时监控
adb shell dmesg -w > /tmp/dmesg-现场.log &
adb logcat -b all > /tmp/logcat-现场.log &
```

---

## 刷机

```bash
adb reboot bootloader
sleep 8
fastboot boot <path>/刷机包.img
```

如果 `fastboot boot` 卡住或失败：
```bash
fastboot boot 刷机包.img 2>&1 | tee /tmp/flash-fastboot-error.log
fastboot reboot-bootloader
```

---

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

### 3. 基础功能验证
- [ ] 所有基础命令正常工作
- [ ] 新编译的功能符号在 kallsyms 中可见
- [ ] dmesg 无新增的错误/WARNING 日志

### 4. 本次移植功能专项验证（见项目上下文）

### 5. 异常情况处理

#### 5a. 刷机后设备无法进入系统
```bash
fastboot devices
fastboot boot <上一个已知正常的boot.img>
grep -i 'panic\|error\|fail' /tmp/dmesg-现场.log | tail -20
grep -i 'panic\|error\|fail' /tmp/logcat-现场.log | tail -20
```

#### 5b. 功能命令失败
```bash
strace -e syscall_type 命令 2>&1     # 追踪 syscall 层
dmesg | grep '模块名:'               # 检查内核侧是否收到命令
```

#### 5c. 编译失败
```bash
# 1. 获取构建日志
gh run view --log 2>&1 | tee /tmp/build-失败.log
# 2. 定位错误类型
grep -n 'error:\|Error:\|FAILED\|fatal' /tmp/build-失败.log | head -20
# 3. Python 脚本错误
grep -B5 'IndentationError\|SyntaxError\|FileNotFoundError\|ImportError' /tmp/build-失败.log
# 4. C 编译错误
grep -B2 'error:' /tmp/build-失败.log | grep '\.c\|\.h' | head -10
# 5. 链接错误
grep -B1 'undefined reference' /tmp/build-失败.log | head -10
# 6. 配置错误
grep 'config\|merge_config' /tmp/build-失败.log | grep -i 'error\|fail'
# 7. 修复后记录经验到 ERRORS.md
```

---

# 第 II 部分：项目上下文

> **每次新项目时，复制此段并重写。以下为当前 SUSFS v1.5.5 → v2.2.0 移植的上下文。**

### 项目标识
- **项目名**：SUSFS 移植
- **基线版本**：v1.5.5（kernel-4.19 分支，实际版本号 v1.5.9）
- **目标版本**：v2.2.0（OpenELA-4.14.y-susfs 分支）
- **内核版本**：4.19.304（Qualcomm sm8250/kona）
- **KSU 变体**：KSUN-legacy（rifsxd/KernelSU-Next legacy 分支）

### 函数签名映射
| 版本 | 调用约定 | 返回类型 | 参数 |
|------|---------|---------|------|
| v1.5.5（基线） | `func(struct xxx* __user)` | `int` | 单指针，返回 0=成功 |
| v2.2.0（目标） | `func(void __user **)` | `void` | 双指针，写 err 字段 |

### 关键锚点（注入用）
| 文件 | 锚点 | 说明 |
|------|------|------|
| `susfs.h` | `/* susfs_init */` | 所有结构体/声明插在此标记前 |
| `susfs.c` | `/* susfs_init */` | 所有新函数插在此标记前 |
| `susfs_def.h` | `#define CMD_SUSFS_ADD_SUS_MOUNT` | 新 CMD 插在此行前 |
| `stat.c` | `extern void susfs_sus_ino_for_generic_fillattr` | VFS 调用点替换 |
| `task_mmu.c` | `extern void susfs_sus_ino_for_show_map_vma` | VFS 调用点替换 |

### Kconfig 命名空间
- 前缀：`CONFIG_KSU_SUSFS_`
- 定义位置：`kernel-patches/ksu.config`（值） + GHA workflow 中 printf 注册（菜单）
- 示例：`CONFIG_KSU_SUSFS_SUS_PATH`, `CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING`

### 通信通道
| 路径 | 用途 | 协议 |
|------|------|------|
| IOCTL(fd 5, KSU_IOCTL_SUSFS, ...) | ksu_susfs 工具调用 | 返回 int |
| reboot(0xDEADBEEF, 0xFAFAFAFA, CMD, &struct) | ksud 调用 | struct { data[N]; int err; }，err 初始=126 |

### 当前移植进度
- ✅ Batch 0: 基础 SUSFS v1.5.5 集成
- ✅ Batch 1: AVC_LOG + ENABLE_LOG（新 v2.2.0 协议）
- 🚧 Batch 2: hide_mnts + fillattr + map_vma + path_loop（构建验证中）
- ❌ Batch 3+: sdcard_monitor + open_redirect_spoof + 剩余功能

### 本批次测试命令
```bash
# Batch 2 验证
adb shell cat /proc/kallsyms | grep 'susfs_set_hide_sus_mnts\|susfs_generic_fillattr_spoofer\|susfs_show_map_vma_spoofer\|susfs_add_sus_path_loop\|susfs_extra_works'
```
