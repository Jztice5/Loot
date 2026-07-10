# Loot Crypto 行情数据 Provider 设计文档 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Implemented |
| 版本 | 0.1 |
| 日期 | 2026-07-10 |
| 适用范围 | Phase 0：Crypto 只读行情输入 |
| 代码位置 | `src/loot/contracts/market_data.py`、`src/loot/domains/crypto/market_data.py` |

## 1. 设计目标

本设计为 Crypto bounded context 接入第一版行情数据源。

目标：

- 定义标准 K 线和行情快照契约。
- 提供 `CryptoMarketDataProvider` 抽象，隔离具体交易所。
- 提供 `FakeCryptoProvider`，用于本地闭环、Golden Case 和无外网测试。
- 提供 `OkxRestCryptoProvider`，读取 OKX public REST K 线。
- 默认只返回已收盘 K 线；盘中未收盘 K 线必须显式开启。
- 保持只读边界，不接账户、不接私有 API、不下单。

非目标：

- 不实现 WebSocket。
- 不实现 API key、账户、余额、订单、持仓同步。
- 不实现 PreFilter、Policy Gate、Agent 或 Signal 状态迁移。
- 不做跨交易所聚合和 fallback 选择。

## 2. 调用链

```text
Scheduler / Worker
-> CryptoMarketDataProvider.fetch_recent_bars
-> MarketBar
-> MarketSnapshot
-> Crypto PreFilter
-> CandidateEvent
```

Provider 只能生成行情事实，不能直接产生 Signal，也不能绕过 Policy Gate。

## 3. 契约

### 3.1 MarketBar

`MarketBar` 表达一根标准化 K 线：

- `provider`
- `provider_event_id`
- `market`
- `instrument_id`
- `venue`
- `symbol`
- `timeframe`
- `opened_at`
- `closed_at`
- `open_price`
- `high_price`
- `low_price`
- `close_price`
- `volume`
- `quote_volume`
- `is_closed`
- `received_at`

业务规则：

- 时间必须是 timezone-aware，并归一化为 UTC。
- `open/high/low/close` 必须为正。
- `high_price` 必须覆盖 open、close、low。
- `low_price` 必须覆盖 open、close、high。
- `closed_at` 必须晚于 `opened_at`。
- `received_at` 不能早于 `opened_at`。
- `is_closed=False` 可以进入快照，但不能发布 `MarketBarClosedEvent`。

### 3.2 MarketSnapshot

`MarketSnapshot` 表达一个标的、一个周期上的行情窗口。

业务规则：

- `bars` 至少一根。
- `bars` 在契约中保存为 tuple，避免消费者在内存中追加或重排行情事实。
- 所有 `bars` 必须与 snapshot 的 market、instrument、timeframe、source_provider 一致。
- `bars` 必须按 `opened_at` 升序排列。
- 同一 snapshot 内 `provider_event_id` 不能重复。
- `snapshot_key` 是 replay 和幂等输入，不是用户展示字段。
- `latest_bar` 可能是未收盘 K 线；PreFilter 默认应使用 `latest_closed_bar`。

### 3.3 MarketBarClosedEvent

`MarketBarClosedEvent` 预留给后续事件总线使用。

业务规则：

- 只能发布 `is_closed=True` 的 K 线。
- event identity 必须与 bar identity 一致。
- `dedupe_key` 不能为空。

## 4. Provider

### 4.1 CryptoMarketDataProvider

市场领域依赖抽象接口：

```text
fetch_recent_bars(
    instrument,
    timeframe,
    limit,
    include_unclosed=False,
) -> MarketSnapshot
```

所有实现必须满足：

- 只读取公开行情。
- 只返回标准契约。
- 默认返回已收盘 K 线。
- 如果调用方需要盘中最新 K 线，必须显式传 `include_unclosed=True`。
- 不读取账户、余额、订单或交易权限。
- 不直接写 Candidate、Signal 或 Position。

### 4.2 FakeCryptoProvider

用途：

- 无外网单元测试。
- Golden Case 固定输入。
- FakePreFilter 和第一条最小闭环的行情入口。

行为：

- 生成稳定递增的 K 线。
- `provider_event_id` 可复现。
- 默认所有 K 线均为已收盘。

### 4.3 OkxRestCryptoProvider

用途：

- 第一版真实 Crypto 行情源。
- 本地 smoke 验证公共 K 线标准化。
- 后续 Shadow 模式只记录不提醒。

边界：

- 使用 OKX public market candles REST 接口。
- 不需要 API key。
- 只接受 `Instrument.venue = OKX`。
- 当前只实现最近 K 线读取，不实现历史翻页和 WebSocket。
- 默认过滤 `confirm != "1"` 的未收盘 K 线；显式 `include_unclosed=True` 时才保留。

OKX 原始 K 线数组按字段顺序解析：

```text
ts, open, high, low, close, volume, volume_ccy, volume_ccy_quote, confirm
```

其中 `confirm == "1"` 映射为 `is_closed=True`。

## 5. 幂等与 Replay

当前稳定键：

```text
provider_event_id = provider + venue + symbol + timeframe + opened_at
snapshot_key = provider + instrument_id + timeframe + latest provider_event_id
```

后续接 Redis Streams 或 PostgreSQL 时：

- 同一 `provider_event_id` 只能生成一条标准 K 线事实。
- `MarketBarClosedEvent.dedupe_key` 应包含 provider、instrument、timeframe 和 opened_at。
- Replay 使用 `snapshot_key` 锁定输入窗口。

## 6. 错误处理

| 场景 | 行为 |
|---|---|
| Instrument 不是 CRYPTO | 抛出 `ValueError` |
| OKX Provider 收到非 OKX venue | 抛出 `ValueError` |
| limit 小于 1 或超过 Provider 上限 | 抛出 `ValueError` |
| OKX 响应 code 非 0 | 抛出 `CryptoProviderError` |
| OKX 响应缺少数据行 | 抛出 `CryptoProviderError` |
| OKX 单行字段不足 | 抛出 `CryptoProviderError` |

## 7. 验证

已通过：

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
py -3.12 -m unittest discover -s tests -p 'test_*.py'
```

结果：

```text
Ran 30 tests
OK
```

编译检查：

```powershell
py -3.12 -m compileall src tests
```

结果：通过。

真实 OKX public REST smoke 已通过，输出格式如下：

```text
okx.public_rest 2 BTC-USDT <close_price>
```

PyCharm Terminal smoke 已验证默认返回已收盘 K 线：

```text
is_closed= True
latest_closed_same= True
```

## 8. 后续扩展

下一步建议：

1. 增加 `FakeCryptoPreFilter`，从 `MarketSnapshot.latest_closed_bar` 产生 `CandidateEvent`。
2. 建立 Crypto 第一批 Golden Case。
3. 将 `MarketBarClosedEvent` 接入事件消费者和幂等账本。
4. 为 OKX Provider 增加历史缺口补拉和数据质量标记。
5. 再进入 Policy Gate、DecisionTicket 和 Signal State Machine 闭环。
