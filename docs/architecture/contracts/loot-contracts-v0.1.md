# Loot 核心契约设计文档 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Implemented |
| 版本 | 0.1 |
| 日期 | 2026-07-10 |
| 最后实现校准 | 2026-07-16 |
| 依赖 | Loot 系统宏观架构、自选与持仓信号监控闭环 |
| 适用范围 | Phase 0：Architecture Foundation |

## 1. 设计目标

本设计定义 Loot 第一批跨模块强类型契约，供 Platform、Market Domain、Signal、Alert 和后续 Replay 使用。

目标：

- 先定义稳定契约，再实现生产者和消费者。
- 所有跨模块事件使用统一 `EventEnvelope`。
- 手动持仓变化只通过 `PositionEvent` 追加记录。
- Signal 变化只通过 Policy Gate 签发的 `DecisionTicket` 和状态机表达，不允许
  Agent、Skill 或确定性分析器直接写状态。
- 所有时间字段内部统一为 UTC aware datetime。

非目标：

- 不定义数据库表结构和迁移。
- 不实现状态机执行引擎。
- 不实现 API、Provider、Agent、Skill Runtime。
- 不定义三市场专属业务规则。

## 2. 契约归属与迁移状态

```text
src/loot/contracts/
  base.py          Pydantic 不可变基础模型与共享校验
  enums.py         市场、状态、方向、优先级等枚举
  events.py        EventEnvelope
  market.py        Instrument、PriceZone
  market_data.py   MarketBar、MarketSnapshot、MarketBarClosedEvent
  portfolio.py     WatchItem、TradingPlan、Position、PositionEvent
  monitoring.py    MonitoringSubscription、CandidateEvent
  signals.py       EvidenceSet、DecisionProposal、PolicyEvaluation、
                   DecisionTicket、SignalInstance、SignalEvent
```

REQ-0007 已完成统一迁移：`DecisionProposal` 只表达 Policy 前建议，
`DecisionTicket` 只表达 Policy Gate 签发的授权凭证，代码中不保留旧语义别名。

## 3. 契约原则

- 契约模型默认不可变，防止消费者在内存中悄悄修改事实。
- 契约模型禁止额外字段，避免生产者和消费者契约漂移。
- 跨模块时间必须包含 timezone，并在模型中归一化为 UTC。
- 生命周期时间必须保持单向推进，例如 `updated_at` 不能早于 `created_at`，`expires_at` 不能早于触发或观测时间。
- 枚举值使用业务协议中的大写状态或标准周期字符串。
- 金额、价格、数量和风险倍数使用 `Decimal`。
- 幂等键、路由键、producer、event_type 等关键文本字段不能为空。
- `Direction` 的 `LONG`、`SHORT`、`NEUTRAL` 表达市场判断或 TradingPlan 偏向，不代表
  下单；`PositionSide` 只表达用户手工维护的实际持仓方向。

## 4. 关键契约

### 4.1 EventEnvelope

所有事件生产者和消费者共享：

- `event_id`
- `event_type`
- `event_version`
- `occurred_at`
- `producer`
- `correlation_id`
- `causation_id`
- `partition_key`
- `payload`

消费者必须以 `event_id` 或业务 `dedupe_key` 实现幂等。

### 4.2 MarketBar、MarketSnapshot 和 MarketBarClosedEvent

`MarketBar` 是 Provider 标准化后的 K 线事实，要求：

- provider、provider_event_id、venue、symbol 不能为空。
- open、high、low、close 必须为正。
- volume 不能为负。
- opened_at、closed_at、received_at 必须是 UTC aware datetime。
- high/low 必须覆盖 open/close，避免基础行情形态失真。
- `is_closed=True` 时 received_at 不能早于 closed_at。

`MarketSnapshot` 是一次预筛选或 replay 的行情窗口，要求：

- 所有 bars 属于同一 market、instrument、timeframe 和 source_provider。
- bars 在契约内保存为 tuple，避免消费者追加或重排行情事实。
- bars 按 opened_at 升序排列。
- 同一 snapshot 内 provider_event_id 不能重复。
- `latest_bar` 可能未收盘，策略默认应使用 `latest_closed_bar`。
- snapshot_content_hash 基于完整有序 K 线窗口的 canonical 规范化市场输入生成；as_of 和
  received_at 是采集审计时间，不进入业务输入指纹，避免同一历史窗口重抓时身份漂移。
- snapshot_key 和 snapshot_id 必须绑定完整窗口内容；不同窗口长度、历史修正或闭合
  状态变化不得复用 identity。
- as_of 不能早于任何已收盘 K 线的 closed_at。

`MarketBarClosedEvent` 预留给后续事件总线使用，只允许发布已确认收盘 K 线。

### 4.3 CandidateEvent 与方向语义

Crypto 方向性 Candidate 必须包含 `direction: Direction`：

- 上破结构边界使用 `STRUCTURE_BREAKOUT + LONG`。
- 下破结构边界使用 `STRUCTURE_BREAKOUT + SHORT`。
- 不表达方向的信息或数据质量候选可以使用 `NEUTRAL`。
- Candidate `dedupe_key` 必须绑定 direction；相同 Snapshot 上的 LONG 和 SHORT 不能
  复用身份。
- TradingPlan.direction 和 PositionSide 可以影响后续 Policy、优先级和提醒语义，
  但不能改写由市场事实计算出的 Candidate.direction。
- 现货标的允许形成 SHORT 市场判断；是否可建立空头仓位属于 InstrumentPolicy 和
  Actionability，不属于 Candidate 的事实判断。

方向性 Evidence 输出、DecisionProposal、DecisionTicket、SignalInstance 和 SignalEvent
必须保持同一 direction。Policy Gate 可以拒绝或延后，但不能把 LONG 改写为 SHORT，
反之亦然；如需调整目标状态、可操作性或证据，必须生成新 Proposal。

### 4.4 PositionEvent

当前支持：

```text
OPEN
ADD
REDUCE
MOVE_STOP
CLOSE
```

`CANCEL_PLAN` 属于 TradingPlan 生命周期，不属于 PositionEvent。

规则：

- `OPEN`、`ADD`、`REDUCE` 必须携带 `quantity_delta` 和 `execution_price`。
- `MOVE_STOP` 必须携带 `new_stop`。
- 每个事件必须携带 `idempotency_key`。
- 写入后不可更新或删除。

### 4.5 DecisionProposal、PolicyEvaluation、DecisionTicket 和 SignalEvent

`DecisionProposal` 是 Decision Skill 或确定性 Decision Builder 输出的待准入建议，
必须包含 Candidate、Evidence、Skill/规则版本和输入快照引用。Proposal 不能直接进入
Signal State Machine。

Proposal 还必须绑定 signal_id、signal_type、expected_signal_version、WatchItem 版本、
TradingPlan 配置版本、可选 Position 版本和 context_digest，防止审核后上下文变化仍
应用旧建议。

方向性 Proposal 还必须绑定 direction，并与 Candidate、Evidence 和目标 Signal 一致。
direction 必须进入 proposal_digest，禁止在 Policy 审核或 Ticket 签发阶段被静默修改。
`EvidenceSet` 直接保留 `candidate_event_id`、`input_snapshot_id`、direction 和稳定
`dedupe_key`，使 Proposal 前的证据链也可独立回放。

`PolicyEvaluation` 是 Policy Gate 对 Proposal 的审计结果：

```text
APPROVED
REJECTED
DEFERRED
```

PolicyEvaluation 使用 evaluation_request_id 做投递幂等，并使用
`proposal_id + policy_version + evaluation_context_digest` 区分评估事实。
`DEFERRED` 到期或上下文变化后追加新评估，不能被首次结果永久阻塞。

只有 `APPROVED` 才能签发 `DecisionTicket`。Policy Gate 不得静默修改 Proposal；
需要改变目标状态或证据时必须生成新的 Proposal。

`DecisionTicket` 是 Policy Gate 签发的已授权迁移凭证，必须包含：

- `proposal_id`、`policy_evaluation_id` 和 `policy_version`。
- `proposal_digest`，锁定被审核的 Proposal 内容。
- `authorized_transition`，作为状态机唯一读取的目标状态。
- 市场、标的、周期、Signal 和输入快照身份。
- `expected_signal_version`、业务上下文版本和 `context_digest`。
- `issued_at`、`expires_at` 和稳定 `dedupe_key`。

Ticket 写入后不可修改，过期 Ticket 不能改变 Signal。同一 Proposal 整个生命周期最多
签发一张 Ticket。状态机必须从事实源校验 APPROVED PolicyEvaluation、proposal_digest
和上下文版本，不能仅信任调用方构造的 Ticket。

`SignalInstance` 初始化时 `latest_decision_ticket_id` 必须为 null，并携带从 1 开始的
generation 和稳定 setup_key。终态实例不可重置；新市场结构创建下一代实例。任何投影
更新都必须重新运行完整契约校验，不能通过不校验的局部复制形成事实状态。

`SignalEvent` 只表达真实状态变化：

- `from_state` 和 `to_state` 不能相同。
- 事件必须携带 `candidate_event_id`、`decision_proposal_id`、
  `policy_evaluation_id`、`decision_ticket_id` 和 `input_snapshot_id`。
- 事件 direction 必须与 Signal 和授权链一致。
- 去重使用稳定 `dedupe_key`。

## 5. 验证策略

当前使用 `unittest discover` 执行无外部服务依赖的契约和运行时测试：

```bash
py -3.12 -m unittest discover -s tests -p "test_*.py"
```

后续项目骨架稳定后，可切换或补充 pytest。

## 6. 后续扩展

- 按持久化设计补数据库表结构和迁移。
- 在 REQ-0008 将内存授权事实和 Signal 投影迁移到 PostgreSQL 事务与唯一约束。
- Skill Manifest 与 SkillRun 已由
  [Skill Runtime V0.1](../runtime/skill-runtime-v0.1.md)补齐；Guard 输出继续沿用 `PolicyGuardResult`。
- 为 MarketBarClosedEvent 补事件信封映射和持久化幂等键。
- 增加 JSON Schema 导出，服务 API 和事件消费者共享。
