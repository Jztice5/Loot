# 项目 Skills 索引

> 本目录保存可随 Git 在多设备间同步的项目级 Codex skills。

## 权威副本

| Skill | 项目内路径 | 用途 |
|---|---|---|
| `vibe-context-manager` | [vibe-context-manager/SKILL.md](vibe-context-manager/SKILL.md) | 维护 architecture、memory、季度日志、规划、评审、runbook 和 AGENTS |

项目内版本是 Loot 的权威副本。设备上的 `$CODEX_HOME/skills` 只是安装镜像，不应在
多个设备上分别维护不同版本。

## 使用方式

1. 拉取最新 Loot 仓库。
2. 按 [同步项目 Skills](../runbooks/sync-project-skills.md) 将项目副本安装到本机。
3. 新开 Codex 任务，使本机重新发现 skill。
4. 修改 skill 时先改项目副本，验证后同步到本机并提交 Git。

Skill 目录只保存 Codex 运行所需文件；安装说明、变更记录和设备操作放在 docs 与
runbooks，不写入 skill 本体。
