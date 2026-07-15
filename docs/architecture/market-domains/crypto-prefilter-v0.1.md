# Loot Crypto Structure PreFilter V0.1

| 属性 | 值 |
|---|---|
| 状态 | Implemented |
| 版本 | 0.1 |
| 日期 | 2026-07-15 |
| 需求 | REQ-0005 |
| 依赖 | Crypto Golden Cases V0.1 |

## 1. 目标

在 Crypto 行情 Provider 与昂贵分析链路之间增加确定性预筛选，只让 Golden Case 已定义
的收盘结构突破生成 CandidateEvent。无候选结果同样保留稳定原因和结构边界，便于审计、
指标和 Replay。

## 2. 非目标

- 不接 Agent、LLM、Skill Runtime、Policy Gate 或 Alert。
- 不加入成交量确认、ATR、突破容差、自适应窗口或多周期共振。
- 不读取 TradingPlan 或 Position 改写市场结构真假。
- 不处理 funding、OI、liquidation、order book 或信息事件。

## 3. 输入输出

```text
CryptoPreFilterInput
- snapshot: MarketSnapshot
- watch_item_id: UUID
- position_id: UUID | null

CryptoPreFilterResult
- rule_version
- reason
- candidate: CandidateEvent | null
- reference_high: Decimal | null
- reference_low: Decimal | null
- trigger_bar_id: UUID | null
```

`position_id` 只透传到 Candidate 供后续 Policy 和提醒关联，不参与方向和结构判断。

## 4. 确定性规则

规则版本固定为 `crypto.structure-breakout.v1`，与 Golden Case schema 一致：

```text
closed_bars < 4
-> INSUFFICIENT_CLOSED_HISTORY

trigger.close > max(previous_3.high)
-> STRUCTURE_BREAKOUT + LONG

trigger.close < min(previous_3.low)
-> STRUCTURE_BREAKOUT + SHORT

latest unclosed bar 越界但 trigger 未越界
-> UNCLOSED_BAR_IGNORED

otherwise
-> NO_CLOSED_STRUCTURE_BREAK
```

只有两个收盘突破原因会携带 CandidateEvent。PreFilter 可以读取未收盘 bar 判断
`UNCLOSED_BAR_IGNORED` 诊断原因，但绝不据此生成 Candidate。

## 5. Candidate Identity

Candidate dedupe_key 绑定：

```text
rule_version
+ watch_item_id
+ position_id or none
+ instrument_id
+ timeframe
+ snapshot_id
+ candidate_type
+ direction
+ trigger_bar.provider_event_id
```

Candidate UUID 由完整 dedupe_key 生成稳定 UUID。同一输入重复执行返回相同 identity；
Snapshot 内容、WatchItem、Position 上下文、规则版本或方向变化时必须形成不同 identity。
Position 不参与市场方向判断，但它改变 Candidate payload，因此必须进入 identity，避免
相同 ID 对应不同 payload。

## 6. 时间语义

- `occurred_at` 使用触发 K 线 `closed_at`。
- `expires_at` 使用 `snapshot.as_of + 当前 K 线周期长度`。
- 这样实时快照保留一个周期有效期，历史补拉也不会在生成瞬间得到已过期 Candidate。

## 7. 调用链

```text
CryptoMarketDataProvider
-> MarketSnapshot
-> CryptoStructurePreFilter
-> CryptoPreFilterResult
-> [Candidate] Analyzer / Agent / Skill Runtime
-> [No Candidate] audit and metrics only
```

## 8. 测试

- 直接参数化复用 `tests/golden/crypto` 的 8 个版本化案例。
- 覆盖 LONG、SHORT、无候选、历史不足、边界相等和未收盘过滤。
- 覆盖重复输入 identity、方向隔离、Position 不改写方向和非 Crypto 拒绝。
