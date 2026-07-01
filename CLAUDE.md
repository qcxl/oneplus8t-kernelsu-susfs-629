# CLAUDE.md — 项目配置

## Skill routing

当用户请求匹配以下场景时，加载 kport skill 作为流程引导：
skill 文件：`~/.claude/skills/kport/SKILL.md`

- 移植任务（"移植 XX 功能"、"开始 batch"）→ 阶段 1-2
- 编译失败（"编译报错"、"构建失败"）→ 阶段 3
- 刷机验证（"刷机"、"fastboot"）→ 阶段 4
- 提交代码 → 自动运行 pre-flight-check.sh

## kport 配置

项目配置详见 [KPORT.yml](KPORT.yml)。
