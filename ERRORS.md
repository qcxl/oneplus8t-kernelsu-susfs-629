# 错误经验库

> 本文件由 TEST_PROCEDURE.md 拆分而来，每次修复后在此新增条目。
> 主流程文档见 [TEST_PROCEDURE.md](TEST_PROCEDURE.md)。

## 🧠 错误经验库（每次修复后更新）

### E001：`#define` 字符串替换缺少前缀（Batch 1）
**现象**：编译报 `macro name must be an identifier`，生成 `#define #define CMD_...`
**根因**：替换目标字符串 `'CMD_SUSFS_ADD_SUS_MAP'` 不包含前面的 `#define`，替换后变 `#define #define ...`
**教训**：替换预处理指令时必须包含完整的 `#define NAME VALUE` 行，切勿只匹配 NAME
**可自动化**：yes
**对应检查**：pre-flight-check.sh: 不直接检查（语义级），但 pre-flight 会跑 py_compile
**检查清单锚点**：见「替换丢失 `#define`」项 ✅
