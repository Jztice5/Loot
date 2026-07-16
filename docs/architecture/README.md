# 架构文档索引

返回：[项目文档索引](../README.md)

架构文档按设计层级存放：

- [`system/`](./system/)：Loot 系统级宏观架构，描述三市场边界、控制面、市场决策面、信号提醒面、数据平台和 P1 范围。
- [`contracts/`](./contracts/)：跨模块强类型契约，描述枚举、事件信封、持仓事件、DecisionProposal、DecisionTicket 和 SignalEvent。
- [`market-domains/`](./market-domains/)：市场领域组件设计，描述 Crypto、US Equity、A-Share 的数据源、预筛选和领域规则。
- [`runtime/`](./runtime/)：跨模块决策运行时，描述 Proposal、Policy Gate、Ticket、事务、幂等和因果追踪。
- [`context/`](./context/)：项目上下文的时间语义、生命周期和跨任务接手规则。
- [`signal-monitoring/`](./signal-monitoring/)：自选与持仓信号监控闭环设计，描述 WatchItem、TradingPlan、PositionEvent、Market Router、Signal State Machine 和 Alert Loop。
- [`signal-state-machine/`](./signal-state-machine/)：Signal 状态迁移引擎，描述合法迁移、幂等语义、no-op 和错误类型。
- [`testing/`](./testing/)：Golden Case、Replay 输入和评测口径，先固定业务预期再实现算法。

当前实施采用 `Crypto First Vertical Slice`：三市场架构描述是最终边界，不代表并行开发。
Crypto 初版端到端闭环完成验收和复盘前，只实现 Crypto 市场业务与支撑它所必需的平台
能力；US Equity 和 A-Share 的领域实现进入后续阶段。

当前文档：

- [Loot 系统宏观架构设计文档 V0.1](./system/loot-system-architecture-v0.1.md)
- [Loot 核心契约设计文档 V0.1](./contracts/loot-contracts-v0.1.md)
- [Loot 决策运行时与授权链路设计 V0.1](./runtime/decision-flow-v0.1.md)
- [Loot Crypto 行情数据 Provider 设计文档 V0.1](./market-domains/crypto-market-data-provider-v0.1.md)
- [Loot Crypto Structure PreFilter V0.1](./market-domains/crypto-prefilter-v0.1.md)
- [Loot Crypto Golden Cases V0.1](./testing/crypto-golden-cases-v0.1.md)
- [Loot 自选与持仓信号监控闭环设计文档 V0.1](./signal-monitoring/signal-monitoring-loop-design-v0.1.md)
- [Loot Signal State Machine 设计文档 V0.1](./signal-state-machine/loot-signal-state-machine-v0.1.md)
- [Loot 时间上下文模型 V0.1](./context/temporal-context-model-v0.1.md)

后续建议增加：

- `architecture/skill-runtime/`：Skill Manifest、注册、执行、审计、超时和 allowlist 设计。
- `architecture/market-domains/`：Crypto Provider 和 PreFilter 已完成，当前继续推进
  决策链路持久化基线；Crypto 闭环复盘后再分别设计 US Equity 和 A-Share。
- `architecture/replay/`：Golden Case、Replay Engine 和评测口径设计。
