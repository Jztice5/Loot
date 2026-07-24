# 2026-07-24 Crypto 信号准确性优化时机

## 背景

- REQ-0013 已证明 Crypto Run-Once 可以把确定性 Candidate 经 Policy Gate 和 Signal workflow
  写入 PostgreSQL。
- 当前结构突破规则只有 3 根参考 K 线和 1 根收盘触发，尚无历史结果标签或统计评测证据。
- 项目目前不持久化原始 MarketBar、MarketSnapshot 和 Candidate payload，无法从 PostgreSQL
  独立还原当时行情输入。

## 判断过程

- demo 成功、Golden Case 通过和全量测试通过属于工程正确性证据，不能替代交易信号准确性。
- 现在加入 ATR、成交量、多周期、衍生品信息或 Agent，只会增加变量数量，无法判断改动是否
  真正降低假突破或改善期望值。
- 准确性优化应建立在可恢复输入、可重复 Replay、固定结果标签和足够分层样本之上。
- 首轮 200 个已标注 Candidate、LONG/SHORT 各 50 个只是启动探索的最低门槛；生产验收仍需
  根据目标指标和置信区间重新确定样本量。

## 结论

- 保留 `crypto.structure-breakout.v1` 作为可解释基线，不修改 REQ-0013 已完成语义。
- 当前不登记准确性实现需求，只在需求管理中维护 Deferred 观察项和量化触发条件。
- 前置能力完成后，先用 Replay 测量基线，再按单变量顺序增加过滤条件；Agent 和复杂特征最后评估。

## 当前影响

- 本次只更新上下文，不修改代码、数据库和已完成 commit。
- 权威未来触发条件见
  [需求管理中的准确性优化观察项](../../../planning/2026-Q3/需求管理-2026-Q3.md#crypto-信号准确性优化观察项)。
