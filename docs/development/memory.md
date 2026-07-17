# 开发过程记忆

> 当前执行快照唯一入口，只保留项目状态、活跃约束、恢复点和当前验证基线。
> 稳定设计见 [architecture](../architecture/README.md)，过程证据见 [季度日志](log/README.md)。

## 当前状态

- 当前阶段：Phase 0 Architecture Foundation。
- 当前交付策略：Crypto First Vertical Slice；Crypto 初版闭环验收和复盘前不实现
  US Equity 或 A-Share 领域业务。
- 已建立核心 contracts、Signal State Machine v0.1、Crypto 行情 Provider v0.1、
  Golden Cases V0.1、Crypto Structure PreFilter V0.1、Candidate 到 Signal 授权链路，
  以及 REQ-0008 的 PostgreSQL Schema、migration、Repository 和持久化 Signal workflow。
- 当前代码入口：`main.py` 仍是示例；核心代码位于 `src/loot/contracts`、
  `src/loot/signals` 和 `src/loot/domains/crypto`。
- 需求状态与执行队列：[需求管理 2026-Q3](../planning/2026-Q3/需求管理-2026-Q3.md)。

## 当前执行与恢复点

- 活跃需求：`REQ-0008` Crypto 决策链路持久化可靠性基线，状态为 In Progress。
- 恢复动作：先由用户在 `loot_test` 应用 `20260716_0001` migration，再通过 DBX 验收
  10 张表、索引、约束和权限；随后配置 `LOOT_TEST_DATABASE_URL`，执行 PostgreSQL
  端到端测试并修复真实数据库差异，最后在 `loot_dev` 应用同一 migration。
- memory 不复制 Planned 队列；需求顺序变化只更新需求管理。

## 当前实现差异

- PostgreSQL 持久化实现已进入代码，但 `loot_test` 尚未应用 migration；当前只能确认
  68 个非数据库测试通过，真实重启幂等、事务回滚和数据库权限仍待集成测试验收。
- Skill Runtime、Agent、Alert 和最小 Replay 尚未实现。

稳定边界、完整设计链和模块不变量只在 [AGENTS.md](../../AGENTS.md) 与
[架构索引](../architecture/README.md) 维护。

## 当前验证基线

验证日期：2026-07-17。

环境：

- Windows，PowerShell。
- Codex bundled Python 3.12.13。
- Git 基线：包含本条记录的当前分支 HEAD；具体提交以 `git log -1 --oneline` 实时结果为准。

已实际执行：

- `python -m pytest -q`：68 个测试通过，1 个 PostgreSQL 集成测试因未配置
  `LOOT_TEST_DATABASE_URL` 而跳过。
- `python -m compileall -q src tests migrations`：通过。
- `python -m alembic upgrade head --sql`：离线 migration SQL 生成通过。
- `python scripts/check_context.py`：通过；55 个 Markdown、137 个本地链接，Skill 镜像一致。

完整环境初始化和验证命令见 [本地运行说明](../runbooks/local-run.md)。旧 macOS 验证结果
保留在对应季度日志中，不再表述为当前机器已复验。
