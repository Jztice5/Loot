# 开发过程记忆

> 当前事实唯一入口，只保留项目状态、活跃约束、验证基线、未完成和下一步。
> 稳定设计见 [architecture](../architecture/README.md)，过程证据见 [季度日志](log/README.md)。

## 当前状态

- 项目定位：面向个人自选与手动持仓的多市场信号监控系统。
- 当前阶段：Phase 0 Architecture Foundation。
- 已建立核心 contracts、Signal State Machine v0.1、Crypto 行情 Provider v0.1，并完成
  REQ-0009 地基不变量修正。
- 当前代码入口：`main.py` 仍是示例；核心代码位于 `src/loot/contracts`、
  `src/loot/signals` 和 `src/loot/domains/crypto`。
- 当前业务焦点：先完成 `REQ-0006` Crypto Golden Case，再实现 `REQ-0005` PreFilter。
- 当前季度规划：[规划总览 2026-Q3](../planning/2026-Q3/规划总览-2026-Q3.md)。
- 当前需求状态：[需求管理 2026-Q3](../planning/2026-Q3/需求管理-2026-Q3.md)。
- 当前上下文框架已完成长期开发加固和 macOS 适配：根 README 不再复制动态状态，
  AGENTS 按任务加载设计，`make context-check` 提供自动健康检查。
- 项目级 `vibe-context-manager` 权威副本位于
  `docs/skills/vibe-context-manager/SKILL.md`，全局安装目录只是镜像。

## 当前设计主线

```text
WatchItem / TradingPlan / PositionEvent
-> Market Router
-> Market Domain PreFilter
-> CandidateEvent
-> Deterministic Analyzer / Market Agent
-> EvidenceSet
-> DecisionProposal
-> Policy Gate
-> PolicyEvaluation
-> DecisionTicket
-> Signal State Machine
-> SignalEvent
-> Alert Center
-> User Action
-> PositionEvent
```

详细不变量和模块边界以 [AGENTS.md](../../AGENTS.md) 与
[架构索引](../architecture/README.md) 为准，不在 memory 重复维护。

## 活跃约束和差异

- V1 不连接交易账户，不自动下单，不做全市场扫描。
- 三个市场保持独立 bounded context；市场路由必须确定性执行。
- Agent 只能生成 DecisionProposal，Policy Gate 批准后才能签发 DecisionTicket。
- Signal State Machine 是 Signal 状态唯一写入口，必须验证持久化授权链和上下文版本。
- 第一条可运行闭环优先使用 FakeProvider 和 Golden Case 验证幂等、迁移和提醒去重。
- 当前 Python `DecisionTicket` 仍表达 Policy 前建议；REQ-0007 前必须迁移为
  `DecisionProposal`，再增加 Policy 后的新 Ticket。
- Persistence、migrations、Skill Runtime 和 Alert 尚未实现。

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

## 关键历史索引

| 日期 | 主题 | 详情 |
| --- | --- | --- |
| 2026-07-10 | 项目上下文分层 | [过程记录](log/2026-Q3/2026-07-10-context-management.md) |
| 2026-07-10 | 核心契约骨架 | [过程记录](log/2026-Q3/2026-07-10-contracts-foundation.md) |
| 2026-07-10 | Signal State Machine v0.1 | [过程记录](log/2026-Q3/2026-07-10-signal-state-machine.md) |
| 2026-07-10 | Crypto 行情 Provider v0.1 | [过程记录](log/2026-Q3/2026-07-10-crypto-market-data-provider.md) |
| 2026-07-14 | 决策链路设计回归 | [过程记录](log/2026-Q3/2026-07-14-decision-flow-design-regression.md) |
| 2026-07-14 | REQ-0009 地基修正 | [过程记录](log/2026-Q3/2026-07-14-req-0009-foundation-invariants.md) |
| 2026-07-14 | 上下文季度化 | [过程记录](log/2026-Q3/2026-07-14-quarterly-doc-organization.md) |
| 2026-07-14 | 上下文长期加固与 macOS 适配 | [过程记录](log/2026-Q3/2026-07-14-context-framework-macos-hardening.md) |

## 未完成

- Crypto Golden Case 和 FakeCryptoPreFilter。
- DecisionProposal、PolicyEvaluation、Policy 后 DecisionTicket 的契约迁移。
- Persistence、migrations、持久化幂等和 outbox。
- Skill Manifest、SkillRun、Guard 输出和 Agent Runtime。

## 下一步

1. 按 `REQ-0006` 定义 Crypto Golden Case 输入和预期。
2. 按 Golden Case 实现 `REQ-0005` Crypto Candidate PreFilter。
3. 按 `REQ-0007` 串联 Proposal、Policy、Ticket 和 Signal State Machine。
4. 按 `REQ-0008` 设计持久化消费、SignalTransition 和 outbox。
5. 再开始 Skill Runtime、Agent 和 Alert 接入。
