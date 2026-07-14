# 开发过程索引

> 大功能点的过程记录放在这里；`../memory.md` 只保留项目总览、当前状态和入口链接。

## 记录列表

| 日期 | 主题 | 文档 | 关键词 |
| --- | --- | --- | --- |
| 2026-07-10 | 设计上下文分层与维护机制 | [2026-07-10-context-management.md](2026-07-10-context-management.md) | `architecture`、`memory`、`log`、`review`、`runbook`、`AGENTS` |
| 2026-07-10 | 核心契约骨架 | [2026-07-10-contracts-foundation.md](2026-07-10-contracts-foundation.md) | `contracts`、`EventEnvelope`、`PositionEvent`、`SignalEvent`、`unittest` |
| 2026-07-10 | Signal State Machine v0.1 | [2026-07-10-signal-state-machine.md](2026-07-10-signal-state-machine.md) | `SignalStateMachine`、`DecisionTicket`、`SignalEvent`、`idempotency` |
| 2026-07-10 | Crypto 行情数据 Provider v0.1 | [2026-07-10-crypto-market-data-provider.md](2026-07-10-crypto-market-data-provider.md) | `MarketBar`、`MarketSnapshot`、`FakeCryptoProvider`、`OKX` |
| 2026-07-10 | 日终收尾与需求规划 | [2026-07-10-day-closeout.md](2026-07-10-day-closeout.md) | `closeout`、`需求管理`、`REQ-0005`、`REQ-0006`、`REQ-0007` |
| 2026-07-14 | 决策链路设计回归 | [2026-07-14-decision-flow-design-regression.md](2026-07-14-decision-flow-design-regression.md) | `DecisionProposal`、`PolicyEvaluation`、`DecisionTicket`、`Golden Case` |
| 2026-07-14 | 第二轮地基约束收敛 | [2026-07-14-foundation-constraints.md](2026-07-14-foundation-constraints.md) | `snapshot_content_hash`、`DEFERRED`、`context_digest`、`generation` |
| 2026-07-14 | REQ-0009 地基不变量修正 | [2026-07-14-req-0009-foundation-invariants.md](2026-07-14-req-0009-foundation-invariants.md) | `canonical hash`、`closed_at`、`full validation`、`payload fingerprint` |

新过程记录可从 [TEMPLATE.md](TEMPLATE.md) 复制结构。

## 记录原则

- 记录“为什么这么判断”，不只记录“改了什么”。
- 关键契约、状态机、幂等键、命令和验证结果要保留。
- 发现的新问题也写下来，方便下一次接着做。
