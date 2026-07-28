# Loot

Loot the market before it loots you.

Loot 是一个面向个人自选与手动持仓的多市场信号监控系统，目标是持续跟踪 Crypto、美股和 A 股中的关键价格结构、量价变化和信息事件，在值得关注的状态变化发生时提醒用户，减少反复看盘。

当前执行状态与验证基线只在[开发过程记忆](docs/development/memory.md) 维护；需求状态、
依赖和计划队列只在[规划跨季度索引](docs/planning/README.md) 维护，避免入口摘要与真实进度漂移。

## 核心边界

- V1 只做决策辅助和提醒，不连接交易账户，不自动下单。
- 自选、Trading Plan 和持仓由用户手动维护。
- 持仓变化通过 `PositionEvent` 追加记录，不覆盖历史。
- Crypto、US Equity、A-Share 是三个独立 bounded context。
- Agent 只能编排授权 Skill 并生成 DecisionProposal，不能直接写入 Signal、Position
  或交易指令。
- Policy Gate 只有在批准 Proposal 后才能签发 DecisionTicket。
- Signal State Machine 默认只消费已授权 DecisionTicket，是 Signal 状态唯一写入口；唯一受限
  例外是基于已持久化 `expires_at` 的确定性 `EXPIRED` 收敛，它不伪造或消费 Ticket，也不改变
  市场方向、Policy 或持仓事实。
- MarketSnapshot identity 必须绑定完整输入窗口；已闭合 K 线必须满足时间真实性。
- Ticket 必须绑定授权时的 Signal 与业务上下文版本，状态机从事实源验证授权链。

## 文档入口

- 项目文档总入口：[docs/README.md](docs/README.md)
- 当前项目记忆：[docs/development/memory.md](docs/development/memory.md)
- 架构文档索引：[docs/architecture/README.md](docs/architecture/README.md)
- 系统宏观架构：[docs/architecture/system/loot-system-architecture-v0.1.md](docs/architecture/system/loot-system-architecture-v0.1.md)
- 核心契约设计：[docs/architecture/contracts/loot-contracts-v0.1.md](docs/architecture/contracts/loot-contracts-v0.1.md)
- 决策运行时与授权链路：[docs/architecture/runtime/decision-flow-v0.1.md](docs/architecture/runtime/decision-flow-v0.1.md)
- Crypto 常驻监控 Worker：[docs/architecture/runtime/crypto-monitoring-worker-v0.1.md](docs/architecture/runtime/crypto-monitoring-worker-v0.1.md)
- Runtime Console：[docs/architecture/runtime/runtime-console-v0.1.md](docs/architecture/runtime/runtime-console-v0.1.md)
- Signal State Machine：[docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md](docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md)
- 自选与持仓信号监控闭环：[docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md](docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md)
- Crypto 行情数据 Provider：[docs/architecture/market-domains/crypto-market-data-provider-v0.1.md](docs/architecture/market-domains/crypto-market-data-provider-v0.1.md)

## macOS 快速开始

需要 Python 3.12+。首次克隆或依赖变化后执行：

```bash
make setup
make check
```

运行当前示例入口：

```bash
.venv/bin/python main.py
```

macOS、Linux 和 Windows 的完整环境初始化与验证命令见
[本地运行说明](docs/runbooks/local-run.md)。
