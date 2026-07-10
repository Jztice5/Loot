# Crypto 行情数据 Provider v0.1 过程记录

## 背景

用户确认可以开始接入虚拟货币数据源。当前 Loot 已有核心 contracts 和
Signal State Machine，但缺少行情输入，下一步需要为 Crypto 闭环准备可复现数据源。

## 目标

- 先定义行情数据契约，再实现 Provider。
- 先实现 FakeProvider，保证 Golden Case 和本地测试可复现。
- 接入一个真实但只读的公共 REST K 线源。
- 不触碰交易账户、私有 API、订单、持仓同步和自动交易。

## 判断过程

- 继续遵守“契约优先”的实现顺序。
- Crypto 行情先放在 `domains/crypto`，不抽成三市场通用业务 Provider。
- OKX public REST 只读、无认证，适合作为第一版真实 K 线输入。
- 单测不依赖外网，通过注入 `http_get` 固定响应。
- 真实网络 smoke 作为补充验证，不作为单元测试前置条件。

## 改动点

- 新增 `src/loot/contracts/market_data.py`：
  - `MarketBar`
  - `MarketSnapshot`
  - `MarketBarClosedEvent`
- 新增 `src/loot/domains/crypto/market_data.py`：
  - `CryptoMarketDataProvider`
  - `FakeCryptoProvider`
  - `OkxRestCryptoProvider`
  - `CryptoProviderError`
- 新增契约和 Provider 单元测试。
- 新增 Crypto 行情 Provider 设计文档。
- 更新 docs 索引、memory、runbook 和计划。

## 验证

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
py -3.12 -m unittest discover -s tests -p 'test_*.py'
```

结果：

```text
Ran 26 tests
OK
```

```powershell
py -3.12 -m compileall src tests
```

结果：通过。

真实 OKX public REST smoke 通过，输出格式：

```text
okx.public_rest 2 BTC-USDT <close_price>
```

## 发现的问题

- 第一次真实 smoke 被 OKX 返回 403，原因是默认 `urllib` 请求没有合适的
  User-Agent。已在 `_default_http_get` 添加只读客户端标识。

## 后续

1. 实现 `FakeCryptoPreFilter`。
2. 从 `MarketSnapshot` 生成第一条 `CandidateEvent`。
3. 准备 Crypto Golden Case，验证重复行情不重复产生候选。
4. 再接 `DecisionTicket -> SignalStateMachine` 最小闭环。
