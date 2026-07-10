# Loot 核心契约设计文档 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Proposed |
| 版本 | 0.1 |
| 日期 | 2026-07-10 |
| 依赖 | Loot 系统宏观架构、自选与持仓信号监控闭环 |
| 适用范围 | Phase 0：Architecture Foundation |

## 1. 设计目标

本设计定义 Loot 第一批跨模块强类型契约，供 Platform、Market Domain、Signal、Alert 和后续 Replay 使用。

目标：

- 先定义稳定契约，再实现生产者和消费者。
- 所有跨模块事件使用统一 `EventEnvelope`。
- 手动持仓变化只通过 `PositionEvent` 追加记录。
- Signal 变化只通过状态迁移事件表达，不允许 Agent 直接写状态。
- 所有时间字段内部统一为 UTC aware datetime。

非目标：

- 不定义数据库表结构和迁移。
- 不实现状态机执行引擎。
- 不实现 API、Provider、Agent、Skill Runtime。
- 不定义三市场专属业务规则。

## 2. 初始代码位置

```text
src/loot/contracts/
  base.py          Pydantic 不可变基础模型与共享校验
  enums.py         市场、状态、方向、优先级等枚举
  events.py        EventEnvelope
  market.py        Instrument、PriceZone
  market_data.py   MarketBar、MarketSnapshot、MarketBarClosedEvent
  portfolio.py     WatchItem、TradingPlan、Position、PositionEvent
  monitoring.py    MonitoringSubscription、CandidateEvent
  signals.py       EvidenceSet、DecisionTicket、SignalInstance、SignalEvent
```

## 3. 契约原则

- 契约模型默认不可变，防止消费者在内存中悄悄修改事实。
- 契约模型禁止额外字段，避免生产者和消费者契约漂移。
- 跨模块时间必须包含 timezone，并在模型中归一化为 UTC。
- 生命周期时间必须保持单向推进，例如 `updated_at` 不能早于 `created_at`，`expires_at` 不能早于触发或观测时间。
- 枚举值使用业务协议中的大写状态或标准周期字符串。
- 金额、价格、数量和风险倍数使用 `Decimal`。
- 幂等键、路由键、producer、event_type 等关键文本字段不能为空。

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

`MarketSnapshot` 是一次预筛选或 replay 的行情窗口，要求：

- 所有 bars 属于同一 market、instrument、timeframe 和 source_provider。
- bars 按 opened_at 升序排列。
- 同一 snapshot 内 provider_event_id 不能重复。
- snapshot_key 作为 replay 和幂等输入。

`MarketBarClosedEvent` 预留给后续事件总线使用，只允许发布已确认收盘 K 线。

### 4.3 PositionEvent

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

### 4.4 DecisionTicket 和 SignalEvent

`DecisionTicket` 是 Decision Skill 输出的待准入决策，必须包含 evidence 引用和 skill 版本。

`SignalEvent` 只表达真实状态变化：

- `from_state` 和 `to_state` 不能相同。
- 事件必须携带 `decision_ticket_id`。
- 去重使用稳定 `dedupe_key`。

## 5. 验证策略

当前使用 `unittest discover` 执行无外部测试依赖的契约测试：

```bash
py -3.12 -m unittest discover -s tests -p "test_*.py"
```

后续项目骨架稳定后，可切换或补充 pytest。

## 6. 后续扩展

- 按持久化设计补数据库表结构和迁移。
- 为 Signal State Machine 增加合法迁移表。
- 为 Skill Manifest、SkillRun 和 Guard 输出补契约。
- 为 MarketBarClosedEvent 补事件信封映射和持久化幂等键。
- 增加 JSON Schema 导出，服务 API 和事件消费者共享。
