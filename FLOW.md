# 测试流程与移植规范

## 验证流程

每次刷机后按以下顺序验证：

### 1. 冷启动时序验证（首次刷机后必须做）
```
adb wait-for-device && sleep 60    # 等待系统完全启动
adb root
adb shell dmesg > /tmp/dmesg.txt   # 保存完整内核日志
adb logcat -b events -d > /tmp/boot_events.txt  # 保存启动事件

# 关键时间戳
grep "delayed init" /tmp/dmesg.txt          # workqueue 执行时间（应在 ~33s）
grep "manager UID set" /tmp/dmesg.txt       # track_throne 成功时间
grep "seccomp_bypass" /tmp/dmesg.txt        # seccomp_bypass kprobe 注册
grep "ksu_reboot kprobe" /tmp/dmesg.txt     # ksu_reboot kprobe 注册
grep "allowed_for_su" /tmp/dmesg.txt        # allowed_for_su 诊断日志
grep "proc_start" /tmp/boot_events.txt      # App 进程启动时间
grep "boot_progress" /tmp/boot_events.txt   # 启动阶段时间线
grep "post_fs_data_done" /tmp/boot_events.txt # post-fs-data 时间
```

### 2. Fix 逐项验证
见 `ERRORS.md` 中 `F03: Fix 验证` 检查清单。

### 3. App 功能验证
见 `ERRORS.md` 中 `F04: App 功能验证` 检查清单。

### 4. 稳定性验证
连续 3 次冷启动 + 3 次热启动，每次重复步骤 2-3。

## 刷机命令
```bash
# 1. 下载最新构建
gh run download --repo qcxl/oneplus8t-kernelsu-susfs-629 \
  --name kebab-kernel-ksu-debug --dir out/
unzip -o out/kebab-kernel-ksu-debug.zip -d out/

# 2. 刷机
adb reboot bootloader
fastboot flash boot_a out/ksu-debug-boot.img
fastboot reboot

# 3. 等待启动
sleep 60
adb root
```

## 注入脚本规范

- 所有 KSU 内核源码的修改通过 `scripts/inject-*.py` 注入
- 注入脚本中禁止硬编码 `/Users/`、`/home/` 等本地路径
- 注入脚本必须在 GHA workflow 的 "Fix SELinux domain initialization" 阶段运行
- 注入脚本的改动必须同步更新 `ERRORS.md`

## 提交规范

提交前必须通过 `scripts/pre-flight-check.sh`（0 阻断）。
