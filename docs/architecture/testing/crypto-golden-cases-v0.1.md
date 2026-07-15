# Loot Crypto Golden Cases V0.1

| 属性 | 值 |
|---|---|
| 状态 | Implemented |
| 版本 | 0.1 |
| 日期 | 2026-07-15 |
| 需求 | REQ-0006 |
| 适用范围 | Crypto 第一条结构突破闭环 |

## 1. 目标

在实现 Crypto PreFilter 前，用可读、可复现、可执行的固定行情输入定义第一版产品判断。
Golden Case 是后续 PreFilter 和 Replay 的预期事实源，不能由实现代码反推。

## 2. 非目标

- 不实现 CandidateEvent 生产逻辑。
- 不引入 Agent、LLM、Policy Gate 或 Alert。
- 不使用真实历史行情归档。
- 不加入成交量确认、ATR、波动率、自适应窗口或突破容差。

## 3. V0.1 结构规则

只读取 `MarketSnapshot.closed_bars`：

```text
trigger_bar = latest closed bar
reference_bars = 3 closed bars immediately before trigger_bar
reference_high = max(reference_bars.high_price)
reference_low = min(reference_bars.low_price)

trigger_bar.close_price > reference_high
-> STRUCTURE_BREAKOUT + LONG

trigger_bar.close_price < reference_low
-> STRUCTURE_BREAKOUT + SHORT

otherwise
-> NO_CANDIDATE
```

规则边界：

- 必须至少有 4 根已收盘 K 线，才能形成 3 根参考窗口和 1 根触发 K 线。
- 使用严格大于或严格小于；等于结构边界不算突破。
- 只认收盘价确认；影线越界不产生 Candidate。
- 最新未收盘 K 线即使越界，也不参与本次判断。
- LONG 和 SHORT 除高低点与比较方向外保持镜像对称。
- 第一版不要求放量；成交量只保留在 MarketBar 事实中。

## 4. 固定案例

| case_id | 输入特征 | 预期 |
|---|---|---|
| insufficient-closed-history | 已收盘 K 线不足 4 根 | NO_CANDIDATE / INSUFFICIENT_CLOSED_HISTORY |
| range-close-no-break | 影线越过前高但收盘仍在区间 | NO_CANDIDATE |
| closed-at-reference-high-no-break | 收盘价等于结构高点 | NO_CANDIDATE |
| closed-at-reference-low-no-break | 收盘价等于结构低点 | NO_CANDIDATE |
| closed-long-breakout | 已收盘价严格高于前 3 根最高价 | STRUCTURE_BREAKOUT + LONG |
| closed-short-breakdown | 已收盘价严格低于前 3 根最低价 | STRUCTURE_BREAKOUT + SHORT |
| unclosed-long-breakout-ignored | 最新未收盘 K 线向上越界 | NO_CANDIDATE |
| unclosed-short-breakdown-ignored | 最新未收盘 K 线向下越界 | NO_CANDIDATE |

## 5. 固定输入与调用链

固定输入：

`tests/golden/crypto/fixtures/structure-breakout-v0.1.json`

调用链：

```text
versioned JSON fixture
-> FakeCryptoProvider deterministic baseline
-> validated MarketBar facts
-> canonical MarketSnapshot
-> independent expectation
-> REQ-0005 CryptoPreFilter test
-> future Replay
```

JSON 固定业务可读的 OHLCV、闭合状态和预期；加载器使用 FakeCryptoProvider 生成稳定
时间窗口和 Provider identity，再通过 MarketBar 与 MarketSnapshot 契约重新校验事实。

## 6. 后续消费约束

- REQ-0005 已直接参数化复用这些案例，没有复制测试 K 线。
- PreFilter 输出已与 `candidate_type`、`direction`、reason_code 和 snapshot_id 预期对齐。
- PreFilter dedupe_key 在同一案例重复处理时保持稳定，并包含 direction。
- 如果业务规则变化，新增 fixture schema 或规则版本；不得静默改写旧预期。
