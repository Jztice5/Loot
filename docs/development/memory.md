# 开发过程记忆

> 项目级开发记忆，只保留当前状态、关键历史索引和下一步。
> 具体功能点的过程记录通过 [log/](log/README.md) 按季度索引。

## 当前状态

- 项目定位：面向个人自选与手动持仓的多市场信号监控系统。
- 当前阶段：Phase 0 架构基础阶段，已建立核心 contracts、Signal State Machine v0.1、
  Crypto 行情 Provider v0.1，并完成授权链路设计回归和 REQ-0009 地基不变量修正。
- 当前代码入口：`main.py` 仍是 PyCharm 示例脚本；核心契约代码在 `src/loot/contracts`，状态机代码在 `src/loot/signals`，Crypto 行情代码在 `src/loot/domains/crypto`。
- 当前文档入口：`docs/README.md`。
- 当前宏观设计：`docs/architecture/system/loot-system-architecture-v0.1.md`。
- 当前契约设计：`docs/architecture/contracts/loot-contracts-v0.1.md`。
- 当前状态机设计：`docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md`。
- 当前 Crypto 行情设计：`docs/architecture/market-domains/crypto-market-data-provider-v0.1.md`。
- 当前闭环设计：`docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md`。
- 当前决策运行时设计：`docs/architecture/runtime/decision-flow-v0.1.md`。
- 当前季度规划：`docs/planning/2026-Q3/规划总览-2026-Q3.md`。
- 当前需求管理：`docs/planning/2026-Q3/需求管理-2026-Q3.md`。
- 当前上下文维护机制：`docs/README.md` 作为入口，`development/memory.md` 记录状态，`development/log` 记录过程，`reviews` 记录阶段结论，`runbooks` 记录可执行步骤。
- 时间型资料按 `yyyy-Qn` 归档；季度总览、需求管理和开发计划文件名显式带季度标记。
- 项目级 `vibe-context-manager` 权威副本位于
  `docs/skills/vibe-context-manager/SKILL.md`，通过 Git 支持多端同步。

## 设计主线

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

## 关键结论

- 三个市场是独立 bounded context，不抽成一套通用市场规则。
- Agent 只做分析路径选择和 Skill 编排，最多生成 DecisionProposal，不直接写
  Signal、Position 或交易指令。
- Policy Gate 必须为 Proposal 记录 PolicyEvaluation；只有批准时才能签发
  DecisionTicket。
- Signal State Machine 只消费 Policy 后的 DecisionTicket，是 Signal 状态唯一写入口。
- 初始 OBSERVING Signal 由状态机初始化入口根据 MonitoringSubscription 幂等创建；
  Agent、Skill、PreFilter 和 Decision Builder 不能创建 Signal。
- PositionEvent 是持仓历史事实，Position 是当前投影。
- Position 可以影响 Policy、优先级和提醒语义，但不能改变市场结构信号的真假。
- Snapshot identity 必须由完整有序 K 线窗口的 canonical content hash 生成。
- `is_closed=True` 必须满足 received_at 不早于 closed_at。
- PolicyEvaluation 以 evaluation_request_id 做投递幂等，DEFERRED 在新上下文追加评估。
- 一个 Proposal 最多签发一张 Ticket；Ticket 绑定 expected_signal_version、业务版本和
  context_digest，状态机从事实源验证授权链。
- Signal 投影更新必须重新运行完整契约校验；初始 Ticket ID 为空，终态后创建新
  generation，不重置旧实例。
- V1 不接交易账户、不自动下单、不做全市场扫描。
- 第一条可运行闭环应优先使用 FakeProvider 和 Golden Case 验证幂等、状态迁移和提醒去重。
- 上下文维护遵循“稳定设计进 architecture、当前状态进 memory、过程推理进 log、可执行步骤进 runbook、阶段结论进 review”。
- 已创建全局 Codex skill `vibe-context-manager`，可复用到其他长期 vibe coding 项目。
- 第一批 contracts 使用 Pydantic v2 不可变模型，禁止额外字段，并要求跨模块时间为 timezone-aware UTC。
- Signal State Machine v0.1 使用固定合法迁移表和内存幂等账本；同一 `DecisionTicket` 重复消费不会重复生成 `SignalEvent`。
- 内存幂等账本同时保存完整 Ticket payload 指纹；同 ID 不同内容会抛出冲突。
- Signal 状态迁移先归一化 UTC 时间并完整重建 Pydantic 投影，拒绝过期或倒退迁移。
- 当前 `src/loot/contracts/signals.py` 仍把 Policy 前建议实现为 `DecisionTicket`；
  REQ-0007 前必须迁移为 `DecisionProposal`，再增加 Policy 后的新 Ticket。
- Crypto 行情数据 Provider v0.1 已接入：`FakeCryptoProvider` 用于可复现测试，`OkxRestCryptoProvider` 只读访问 OKX public REST K 线。
- 行情数据只进入 `MarketBar` 和 `MarketSnapshot`，不能直接写 Candidate、Signal、Position 或交易指令。
- 已将 `code-standards` Java 版业务注释思路迁移到 Loot Python 代码：
  核心契约 docstring 需要标明业务描述、场景、原因、调用链和规则。
- 当前测试使用标准库 `unittest`，避免 Phase 0 依赖 pytest 安装。

## 历史索引

| 日期 | 主题 | 摘要 | 详情 |
| --- | --- | --- | --- |
| 2026-07-10 | 初始设计分层 | 参考智能客服项目文档体系，建立 Loot 的 architecture / development / planning / reviews / runbooks 分层 | [设计分层校对备忘录](../reviews/2026-Q3/loot-design-layering-review-2026-07-10.md) |
| 2026-07-10 | 上下文维护机制优化 | 补齐过程日志、上下文健康检查 runbook 和 AGENTS 收尾归档规则 | [过程记录](log/2026-Q3/2026-07-10-context-management.md) |
| 2026-07-10 | 核心契约骨架 | 建立 pyproject、src/loot/contracts 和第一批契约测试 | [过程记录](log/2026-Q3/2026-07-10-contracts-foundation.md) |
| 2026-07-10 | Signal State Machine v0.1 | 建立状态机运行时、合法迁移表和内存幂等测试 | [过程记录](log/2026-Q3/2026-07-10-signal-state-machine.md) |
| 2026-07-10 | Crypto 行情 Provider v0.1 | 定义 MarketBar/MarketSnapshot，接入 FakeCryptoProvider 和 OKX public REST K 线 | [过程记录](log/2026-Q3/2026-07-10-crypto-market-data-provider.md) |
| 2026-07-14 | 决策链路设计回归 | 拆分 Proposal、PolicyEvaluation 和 Ticket，固定事务、幂等、失败与追踪边界 | [过程记录](log/2026-Q3/2026-07-14-decision-flow-design-regression.md) |
| 2026-07-14 | 第二轮地基约束 | 用现有代码复现四类风险，补齐 Snapshot、Policy、Ticket 和 Signal 生命周期约束 | [第二轮复核](../reviews/2026-Q3/loot-foundation-second-review-2026-07-14.md) |
| 2026-07-14 | REQ-0009 地基修正 | 落地 Snapshot 内容寻址、闭合时间、Signal 初始化和 Ticket 指纹回归 | [过程记录](log/2026-Q3/2026-07-14-req-0009-foundation-invariants.md) |
| 2026-07-14 | 上下文季度化 | 时间型资料迁入 2026-Q3，稳定知识入口保持固定 | [过程记录](log/2026-Q3/2026-07-14-quarterly-doc-organization.md) |

## 已验证

- `py main.py` 可运行并输出 `Hi, PyCharm`。
- 当前文档已按系统级和闭环级分层。
- `git diff --check` 已用于格式检查。
- `py -3.12 -m compileall src tests`：通过。
- `$env:PYTHONPATH='D:\my-projects\Loot\src'; py -3.12 -m unittest discover -s tests -p 'test_*.py'`：41 tests OK。
- OKX public REST smoke：通过，默认返回 2 根已收盘 BTC-USDT 1H K 线。
- 下一环节需求规划已沉淀到 `docs/planning/2026-Q3/需求管理-2026-Q3.md`。
- 2026-07-14 Markdown 本地链接扫描：通过，无失效链接。
- 2026-07-14 `git diff --check`：通过，仅有仓库行尾转换提示。
- 2026-07-14 第二轮复核：30 tests OK，`compileall` 通过；额外复现 Snapshot identity
  冲突、非法 Signal 投影、提前闭合 K 线和 Ticket payload 冲突漏检。
- 2026-07-14 REQ-0009 回归：上述四类问题均已修复；新增不同窗口、历史内容、闭合
  时间、初始 Signal、UTC/过期投影和 payload 冲突测试，`compileall` 与行长检查通过。

## 未完成

- Persistence 和 migrations。
- FakeCryptoPreFilter 和第一批 Golden Case。
- DecisionProposal、PolicyEvaluation、Policy 后 DecisionTicket 的契约迁移。
- Skill Manifest、SkillRun 和 Guard 输出契约。

## 下一步

优先级建议：

1. 按 `REQ-0006` 定义 Crypto Golden Case 输入和预期。
2. 再按 `REQ-0005` 实现 Crypto Candidate PreFilter。
3. 按 `REQ-0007` 串联 Proposal、PolicyEvaluation、Ticket 和 Signal State Machine。
4. 按 `REQ-0008` 设计持久化 DecisionTicket 消费、SignalTransition 和 outbox。
5. 再开始 Skill Runtime 和 Agent 接入。

日常计划记录放在
[开发计划 2026-Q3](../planning/2026-Q3/开发计划-2026-Q3.md)。
