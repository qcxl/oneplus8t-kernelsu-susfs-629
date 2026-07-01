# 刷机验证流程

> 本文件从 TEST_PROCEDURE.md 拆分而来，专注于刷机操作步骤。
> 移植方法论见 [TEST_PROCEDURE.md](TEST_PROCEDURE.md)。

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
# 0. 获取最新的构建 ID（如果失败 build 不是最新的）
gh run list --repo <owner>/<repo> --limit 1 --json databaseId,status,conclusion
# 指定特定构建 ID
# gh run view --repo <owner>/<repo> <build-id> --log 2>&1 | tee /tmp/build-失败.log

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
