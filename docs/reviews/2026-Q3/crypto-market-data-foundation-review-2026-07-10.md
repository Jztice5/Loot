# Crypto 行情地基评审 2026-07-10

## 评审范围

- `src/loot/contracts/market_data.py`
- `src/loot/domains/crypto/market_data.py`
- Crypto 行情 Provider 架构文档和本地 runbook

本次只评审 K 线标准化地基，不推进 PreFilter、DecisionTicket、Policy Gate 或
Signal State Machine 闭环。

## 总体结论

当前设计方向成立：第一阶段只做 K 线标准化是合适的。它解决了外部交易所字段顺序、
UTC 时间、OHLC 合法性、Provider 边界和 replay 输入稳定性问题。

本次优化后，地基更稳：

- `MarketSnapshot.bars` 改为 tuple，减少消费者在内存中篡改快照的风险。
- 增加 `latest_bar`、`closed_bars`、`latest_closed_bar`，让后续 PreFilter
  可以显式选择已收盘 K 线。
- `OkxRestCryptoProvider` 默认过滤未收盘 K 线；盘中 K 线必须显式
  `include_unclosed=True`。

## 已对齐设计点

- Provider 只读公共行情，不读取账户、不持有 API key、不下单。
- 行情数据只进入 `MarketBar` 和 `MarketSnapshot`，不能直接写 Candidate、
  Signal 或 Position。
- OKX 原始数组被收敛到统一契约，不让后续模块依赖交易所字段顺序。
- 未收盘 K 线语义被保留，但默认不作为策略输入。

## 优化点

| 问题 | 风险 | 处理 |
|---|---|---|
| `MarketSnapshot.bars` 使用 list | 冻结模型仍可能被 append 或 reorder | 改为 tuple |
| OKX 最近 K 线可能包含未收盘数据 | 后续 PreFilter 误判突破或回踩 | 默认过滤未收盘 K 线 |
| 快照缺少安全读取入口 | 后续代码可能直接用 `bars[-1]` | 增加 `latest_closed_bar` |
| runbook 未体现收盘语义 | 人工 smoke 容易误读输出 | 更新输出包含 `is_closed=True` |

## 暂不扩展的内容

暂不加入 ticker、order book、recent trades、funding rate、OI、liquidation、链上数据或新闻。

原因：

- 当前目标是跑通第一条 K 线驱动的监控闭环。
- 过早扩展数据类型会让契约边界变宽，掩盖已收盘 K 线、幂等键和 replay 输入这些基础问题。
- 其他数据类型应该在对应策略需要时，以独立契约和 Provider 方法加入。

## 后续复核清单

1. `FakeCryptoPreFilter` 必须默认读取 `MarketSnapshot.latest_closed_bar`。
2. 如果某个策略需要盘中 K 线，必须在策略或 Provider 调用处显式声明。
3. 接入持久化前，需要固定 `provider_event_id` 和 `snapshot_key` 的数据库唯一约束。
4. 接入 Redis Streams 前，需要将 `MarketBarClosedEvent.dedupe_key` 生成规则落代码。
5. 后续扩展 funding/OI/order book 时，不要塞进 `MarketBar`。

## 验证

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
py -3.12 -m unittest discover -s tests -p 'test_*.py'
```

结果：

```text
Ran 30 tests
OK
```

PyCharm Terminal OKX smoke：

```text
is_closed= True
latest_closed_same= True
closed_bar_count= 2
```
