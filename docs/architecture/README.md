# 架构文档索引

返回：[项目文档索引](../README.md)

架构文档按设计层级存放：

- [`system/`](./system/)：Loot 系统级宏观架构，描述三市场边界、控制面、市场决策面、信号提醒面、数据平台和 P1 范围。
- [`signal-monitoring/`](./signal-monitoring/)：自选与持仓信号监控闭环设计，描述 WatchItem、TradingPlan、PositionEvent、Market Router、Signal State Machine 和 Alert Loop。

当前文档：

- [Loot 系统宏观架构设计文档 V0.1](./system/loot-system-architecture-v0.1.md)
- [Loot 自选与持仓信号监控闭环设计文档 V0.1](./signal-monitoring/signal-monitoring-loop-design-v0.1.md)

后续建议增加：

- `architecture/contracts/`：核心枚举、事件信封、DecisionTicket、SignalEvent 等契约设计。
- `architecture/skill-runtime/`：Skill Manifest、注册、执行、审计、超时和 allowlist 设计。
- `architecture/market-domains/`：Crypto、US Equity、A-Share 的领域规则和差异化设计。
- `architecture/replay/`：Golden Case、Replay Engine 和评测口径设计。
