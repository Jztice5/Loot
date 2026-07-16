# 开发过程记忆

> 当前执行快照唯一入口，只保留项目状态、活跃约束、恢复点和当前验证基线。
> 稳定设计见 [architecture](../architecture/README.md)，过程证据见 [季度日志](log/README.md)。

## 当前状态

- 当前阶段：Phase 0 Architecture Foundation。
- 当前交付策略：Crypto First Vertical Slice；Crypto 初版闭环验收和复盘前不实现
  US Equity 或 A-Share 领域业务。
- 已建立核心 contracts、Signal State Machine v0.1、Crypto 行情 Provider v0.1、
  Golden Cases V0.1、Crypto Structure PreFilter V0.1，以及 Candidate 到 Signal 的
  Phase 0 内存授权链路。
- 当前代码入口：`main.py` 仍是示例；核心代码位于 `src/loot/contracts`、
  `src/loot/signals` 和 `src/loot/domains/crypto`。
- 需求状态与执行队列：[需求管理 2026-Q3](../planning/2026-Q3/需求管理-2026-Q3.md)。

## 当前执行与恢复点

- 活跃需求：无；`REQ-0007` 已完成，当前没有 In Progress 需求。
- 恢复动作：从需求队列首项启动 `REQ-0008` Crypto 决策链路持久化可靠性基线；先读取
  授权链设计和持久化边界，再定义 PostgreSQL Repository、Inbox、Outbox 与事务契约。
- memory 不复制 Planned 队列；需求顺序变化只更新需求管理。

## 当前实现差异

- 当前授权事实和 Signal 幂等账本仍是单进程内存实现，尚不能跨进程恢复；PostgreSQL、
  migrations、Inbox、Outbox 和乐观锁由 REQ-0008 落地。
- Skill Runtime、Agent、Alert 和最小 Replay 尚未实现。

稳定边界、完整设计链和模块不变量只在 [AGENTS.md](../../AGENTS.md) 与
[架构索引](../architecture/README.md) 维护。

## 当前验证基线

验证日期：2026-07-16。

环境：

- Windows，PowerShell。
- Codex bundled Python 3.12.13。
- Git 基线：包含本条记录的当前分支 HEAD；具体提交以 `git log -1 --oneline` 实时结果为准。

已实际执行：

- `PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v`：63 个测试通过。
- `python -m compileall -q src tests scripts`：通过。
- `python scripts/check_context.py`：通过；52 个 Markdown、134 个本地链接，Skill 镜像一致。

完整环境初始化和验证命令见 [本地运行说明](../runbooks/local-run.md)。旧 macOS 验证结果
保留在对应季度日志中，不再表述为当前机器已复验。
