# REQ-0018 Crypto 分析有效性准备度评审

## 评审范围

- 当前 `crypto.structure-breakout.v1` 的真实分析能力。
- Demo、Golden Case、OKX live 验证分别能够证明什么。
- Alert Center 与分析有效性工作的优先顺序。
- V0.2 和历史 Replay 启动前必须补齐的评测门禁。

## 结论

当前系统已经证明“行情可以进入、规则可以确定执行、授权和状态事实可以可靠落库”，但没有证明
LONG/SHORT 具有统计有效性。现有规则只比较最新 H1 收盘价与前 3 根 H1 的高低边界；Demo 的
`LONG / ARMED / POLICY_APPROVED` 证明工程链路，不是实盘策略效果证据；OKX live 验证证明精确
闭合窗口可读取，也不等于当时产生了有效 Candidate。

因此将 Crypto 分析模型 V0.2 与 BTC 一年 Replay 提升为 `REQ-0018`，排在 Alert Center 前面。
在分析结果没有经过同数据、同标签、未见样本对照前，先建设完整提醒链会放大一个尚未验证的
简单规则，产品价值顺序不合理。

## 已确认能力

- MarketBar 和 MarketSnapshot 具备闭合时间、UTC、窗口内容身份与真实 Provider 约束。
- V0.1 有 8 个 Golden Case，覆盖 LONG、SHORT、无候选、边界相等、历史不足和未收盘过滤。
- Candidate 到 Proposal、Policy、Ticket、Signal 和 PostgreSQL 的确定性链路已经打通。
- Worker 能按 H1 精确目标窗口运行、重试和恢复，不重复生成业务事实。

## 关键缺口

- 没有连续历史行情事实、Replay Engine、Outcome Labeler 和统一评测报告。
- 没有 4H 市场状态、ATR/波动、成交量、回踩确认和有意义的 swing structure。
- 没有入场观察区、失效位、目标位和风险收益，无法定义一致的 1R/2R 结果。
- 没有训练/探索与未见验收区间隔离，无法防止过拟合与未来数据泄漏。
- 现有 demo 与 live 数据验证没有形成策略准确性或期望值证据。

## 决策门禁

- 先冻结数据、Replay、标签和评测设计，再实现研究代码。
- 先跑 V0.1 基线，再单变量比较 V0.2 特征，不同时堆叠多个条件。
- 候选不足 200 或 LONG/SHORT 任一不足 50 时，不做上线判断。
- 主指标、保护指标和阈值必须在最终验收区间运行前固定。
- 未达到门禁时允许结论为“V0.2 不上线”，不得为了交付需求而切换默认规则。

## 一句话结论

工程链路已经可信，分析有效性尚未被证明；先做可重复历史验证，再建设面向用户的提醒放大器。
