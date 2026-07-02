# KernelSU Manager 功能对比 —— 标准版 vs KSU-Next

> 撰写日期：2026-06-30
> 标准版：tiann/KernelSU (me.weishu.kernelsu) v3.2.5
> KSU-Next：rifsxd/KernelSU-Next (com.rifsxd.ksunext) v3.2.0

---

## 一、核心差异总结

KSU-Next 本质上是标准 KernelSU 的一个功能分支（fork），两套 Manager App **功能 90% 一致**，差异集中在几个独立 UI 页面和内核侧 SUSFS 支持上。

| 维度 | 标准版 (tiann) | KSU-Next (rifsxd) | 结论 |
|------|:---:|:---:|------|
| 内核兼容性 | GKI 5.10+ | GKI + non-GKI | KSU-Next 胜 |
| SUSFS 隐藏支持 | ❌ | ✅ | KSU-Next 独有 |
| UI 主题数量 | 更多（Material + Miuix 双套） | 单套 | 标准版胜 |
| 独有页面 | 2 个（调色板、关于） | 4 个（备份、开发者、自定义、元模块） | 持平 |
| CLI 功能 | 基本一致 + Magica | 基本一致 + SUSFS | 各有所长 |
| 维护活跃度 | ✅ 高 | ✅ 中 | 标准版胜 |

---

## 二、Manager App 逐项对比

### 2.1 相同功能（29 项）

| 功能 | 说明 |
|------|------|
| 首页仪表盘 | 内核状态、版本、工作状态 |
| SuperUser 授权管理 | 管理允许 root 的应用 |
| 模块管理 | 安装/卸载/启用/禁用 |
| 在线模块仓库 | 浏览/下载模块 |
| 刷写 boot 镜像 | 支持 boot/init_boot |
| 安装/卸载 KernelSU | 一键操作 |
| su 日志查看 | 监控 su 使用记录 |
| 应用配置文件 (AppProfile) | 按应用限制 root 权限 |
| 权限模板 | 预设权限配置 |
| 模板编辑器 | 自定义模板 |
| 模块 action 执行 | 执行模块自定义脚本 |
| WebUI 内嵌 WebView | 模块 Web 界面支持 |
| Material You 动态取色 | Monet 主题 |
| 安全键状态 | 基本完整性检测 |

### 2.2 标准版独有（3 项，可移植）

| 功能 | 移植难度 | 说明 |
|------|----------|------|
| **ColorPalette 调色板** | ✅ 低 | 纯 UI 页面，独立于核心功能 |
| **About 关于页面** | ✅ 低 | 纯 UI 页面，展示版本/许可/贡献者 |
| **Magica 越狱服务** | 🟡 中 | 通过 adb root 实现越狱（KSU-Next 选择移除） |

### 2.3 KSU-Next 独有（4 项，可移植）

| 功能 | 移植难度 | 说明 |
|------|----------|------|
| **BackupRestore 备份恢复** | ✅ 低 | 独立 UI 页面，备份模块/配置 |
| **Developer 开发者选项** | ✅ 低 | 独立 UI 页面，开发者工具 |
| **Customization 自定义页面** | ✅ 低 | 独立 UI 页面，自定义设置 |
| **MetaModule 元模块状态** | ✅ 低 | 独立 UI 页面 + CLI 子命令 |

---

## 三、ksud CLI 逐项对比

### 3.1 标准版 CLIs（KSU-Next 缺失）

| 命令 | 说明 | 移植难度 |
|------|------|----------|
| `module undo-uninstall` | 撤销模块卸载 | ✅ 低（KSU-Next 用 `restore` 替代） |
| `late-load --magica` | 加载 Magica 模块 | 🟡 中 |
| `late-load --post-magica` | 加载后 Magica 处理 | 🟡 中 |

### 3.2 KSU-Next CLIs（标准版缺失）

| 命令 | 说明 | 移植难度 |
|------|------|----------|
| `susfs support` | 检测 SUSFS 支持 | 🟡 中（需内核补丁支持） |
| `susfs version` | 显示 SUSFS 版本 | 🟡 中 |
| `susfs variant` | 显示 SUSFS 变体 | 🟡 中 |
| `susfs features` | 显示已启用功能 | 🟡 中 |
| `module metamodule` | 检查元模块状态 | ✅ 低 |
| `module restore` | 替代 undo-uninstall | ✅ 低（仅重命名） |

---

## 四、内核侧差异

| 内核特性 | 标准版 | KSU-Next | 说明 |
|----------|:---:|:---:|------|
| 通信机制 | ioctl | ioctl | 相同 |
| Hook 方式 | kprobe/syscall | kprobe/syscall | 相同 |
| 模块挂载 | OverlayFS + Magic Mount | OverlayFS + Magic Mount | 相同 |
| **SUSFS 补丁** | ❌ | ✅ | **核心差异** |
| **元模块支持** | ❌ | ✅ | 内嵌内核模块支持 |
| Magica 支持 | ✅ | ❌ | 移除 |
| selinux_hide | ✅ | ✅ | 相同 |
| kernel_umount | ✅ | ✅ | 相同 |
| su_compat | ✅ | ✅ | 相同 |
| sulog | ✅ | ✅ | 相同 |

---

## 五、移植优先级建议

### P0：建议移植（收益明显，成本低）

| 移植项 | 方向 | 理由 |
|--------|------|------|
| **关于页面 → KSU-Next** | 标准版→KSU-Next | 纯 UI，一个页面文件，无依赖 |
| **备份恢复 → 标准版** | KSU-Next→标准版 | 独立 UI，备份模块配置很实用 |
| **module restore/undo** | 对齐命名 | 只是 CLI 命令名差异 |

### P1：可选移植（有用但非必须）

| 移植项 | 方向 | 理由 |
|--------|------|------|
| **ColorPalette → KSU-Next** | 标准版→KSU-Next | 美观改进，不影功能 |
| **Developer → 标准版** | KSU-Next→标准版 | 开发者调试工具 |
| **Customization → 标准版** | KSU-Next→标准版 | 个性化设置 |
| **MetaModule → 标准版** | KSU-Next→标准版 | 模块状态监控 |

### P2：暂不建议移植（成本高或收益低）

| 移植项 | 理由 |
|--------|------|
| **Magica → KSU-Next** | KSU-Next 选择移除，可能有安全考量 |
| **SUSFS → 标准版内核** | 需要整合整个内核补丁集，工作量中到大 |
| **Material/Miuix 双主题** | UI 架构差异大，每页面需要重写 |

---

## 六、代码仓库位置

| 项目 | 仓库 | Manager 源码路径 |
|------|------|-----------------|
| 标准 KernelSU | https://github.com/tiann/KernelSU | `manager/app/src/main/java/me/weishu/kernelsu/` |
| KernelSU-Next | https://github.com/rifsxd/KernelSU-Next | `manager/app/src/main/java/com/rifsxd/ksunext/` |

### 移植参考

- KSU-Next Manager 是基于标准版 fork 的，代码结构高度相似
- 大部分 UI 文件可以逐文件复制并修改包名
- CLI 代码在 `ksud/src/` 目录下（Rust 语言）
- Manager App 使用 Kotlin + Jetpack Compose 编写

---

## 七、当前状态

- 我们使用的是 **KSU-Next Manager v3.2.0**（`com.rifsxd.ksunext`）
- 由于 KSU fd 通信通道尚未建立（等待内核编译修复），Manager 暂时无法连接内核
- 等 kernel hook 修复后，KSU-Next Manager 应能正常识别内核并工作
- 标准版 Manager（`me.weishu.kernelsu`）不兼容 non-GKI 内核，已卸载
