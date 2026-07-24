# Crypto 多空方向模型

## 背景

Crypto Golden Case 原设计只描述“突破”，没有区分向上突破和向下跌破。代码中已经存在
TradingPlan 使用的 `Direction` 和人工持仓使用的 `PositionSide`，但 Candidate 到 Signal
链路没有方向字段，无法稳定表达多空两条分析路径。

## 设计判断

- `Direction.LONG/SHORT/NEUTRAL` 表达市场判断或用户计划偏向，不是交易指令。
- `PositionSide` 只表达用户手工维护的实际持仓，不能替代市场方向。
- Crypto 方向必须从 Candidate 贯穿 Evidence、Proposal、Ticket 和 Signal。
- direction 必须进入 Candidate dedupe、Signal setup 和生命周期身份。
- 向上结构突破为 LONG，向下结构跌破为 SHORT；两套规则保持镜像对称。
- 现货允许形成 SHORT 市场判断，但是否可做空由 InstrumentPolicy 和 Actionability 决定。
- TradingPlan 和 Position 可以影响 Policy、优先级和提醒语义，不能改写市场事实方向。

## 范围

本次只更新稳定设计和 `REQ-0005`、`REQ-0006` 范围，不修改生产代码。代码契约在
Golden Case 固定后随 PreFilter 和授权链路需求实施。

## 验证

- 检查方向字段覆盖 Candidate、Proposal、Ticket、Signal、幂等键和 setup identity。
- 运行项目上下文健康检查，确认文档链接和索引有效。
