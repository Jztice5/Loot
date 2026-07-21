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

- 当前没有 In Progress 需求；下一项工作需先在[需求管理 2026-Q3](../planning/2026-Q3/需求管理-2026-Q3.md)
  登记后再开始。
- `REQ-0008` 已在 `loot_test` 完成真实 PostgreSQL 验收。`loot_dev` 未被本需求触及，后续仅作为
  独立 rollout/deployment 工作处理，不阻塞本次完成。
- 本机集成测试凭据由 `%USERPROFILE%\.loot\database.env` 或环境变量提供；DBX 的
  `loot_app` 测试连接在口令轮换后需要由连接维护者更新。

## 当前实现差异

- PostgreSQL 持久化实现和 `loot_test` migration 已通过真实连接验收；`loot_app` 对
  10 张业务表具备 DML 权限且不能在 `loot` schema 建表。`loot` schema owner 为
  `loot_migrator`，10 张已建业务表 owner 仍为 `postgres`，这是当前非阻塞的运维差异。
- Skill Runtime、Agent、Alert 和最小 Replay 尚未实现。

稳定边界、完整设计链和模块不变量只在 [AGENTS.md](../../AGENTS.md) 与
[架构索引](../architecture/README.md) 维护。

## 当前验证基线

验证日期：2026-07-21。

环境：

- Windows，PowerShell。
- Codex bundled Python 3.12.13。
- Git 基线：包含本条记录的当前分支 HEAD；具体提交以 `git log -1 --oneline` 实时结果为准。

已实际执行：

- `& .\.venv\Scripts\python.exe -m pytest -q`：78 passed（包含 7 个真实 PostgreSQL 集成测试）。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts migrations`：通过。
- `migrations/versions/20260716_0001_crypto_decision_persistence.sql`：已在 `loot_test` 真实执行；
  DBX 验证 10 张业务表、70 个显式业务约束、31 个索引（含 2 个 partial index）。
- `& .\.venv\Scripts\python.exe scripts\check_context.py`：通过，59 个 Markdown、148 个本地链接，
  项目 Skill 与本机镜像一致。

完整环境初始化和验证命令见 [本地运行说明](../runbooks/local-run.md)。旧 macOS 验证结果
保留在对应季度日志中，不再表述为当前机器已复验。
