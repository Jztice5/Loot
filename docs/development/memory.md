# 开发过程记忆

> 当前执行快照唯一入口，只保留项目状态、活跃约束、恢复点和当前验证基线。
> 稳定设计见 [architecture](../architecture/README.md)，过程证据见 [季度日志](log/README.md)。

## 当前状态

- 当前阶段：Phase 0 Architecture Foundation。
- 已建立核心 contracts、Signal State Machine v0.1、Crypto 行情 Provider v0.1，并完成
  REQ-0009 地基不变量修正。
- 当前代码入口：`main.py` 仍是示例；核心代码位于 `src/loot/contracts`、
  `src/loot/signals` 和 `src/loot/domains/crypto`。
- 需求状态与执行队列：[需求管理 2026-Q3](../planning/2026-Q3/需求管理-2026-Q3.md)。

## 当前执行与恢复点

- 活跃需求：无；当前没有 In Progress 需求。
- 恢复动作：从需求管理执行队列选择首项，将原条目从 Planned 改为 In Progress 后开始工作。
- memory 不复制 Planned 队列；需求顺序变化只更新需求管理。

## 当前实现差异

- 当前 Python `DecisionTicket` 仍表达 Policy 前建议；REQ-0007 前必须迁移为
  `DecisionProposal`，再增加 Policy 后的新 Ticket。
- Persistence、migrations、Skill Runtime 和 Alert 尚未实现。

稳定边界、完整设计链和模块不变量只在 [AGENTS.md](../../AGENTS.md) 与
[架构索引](../architecture/README.md) 维护。

## 当前验证基线

验证日期：2026-07-14。

环境：

- macOS，Apple Silicon。
- Python 3.13.9，项目虚拟环境 `.venv`。
- Git 基线：包含本条记录的当前分支 HEAD；具体提交以 `git log -1 --oneline` 实时结果为准。

已实际执行：

- `make setup`：通过；项目及 dev dependencies 以 editable 模式安装。
- `make check`：通过；上下文检查、`compileall` 和 41 个 `unittest` 全部成功。
- `.venv/bin/python main.py`：输出 `Hi, PyCharm`。
- 项目 `vibe-context-manager` 与全局镜像均通过 validator，SHA-256 一致。

完整环境初始化和验证命令见 [本地运行说明](../runbooks/local-run.md)。旧 Windows 验证结果
保留在对应季度日志中，不再表述为当前机器已复验。
