# Loot

Loot the market before it loots you.

Loot 是一个面向个人自选与手动持仓的多市场信号监控系统，目标是持续跟踪 Crypto、美股和 A 股中的关键价格结构、量价变化和信息事件，在值得关注的状态变化发生时提醒用户，减少反复看盘。

当前项目处于 Phase 0 架构基础阶段，已建立 Python 项目骨架、第一批核心 contracts、
Signal State Machine v0.1、Crypto 行情数据 Provider v0.1，并完成 Candidate 到 Signal
授权链路和第二轮地基设计回归。现有 `main.py` 仍是 PyCharm 示例脚本，下一步先按
REQ-0009 修复 Snapshot、闭合时间和状态机不变量，再固化 Crypto Golden Case。

## 核心边界

- V1 只做决策辅助和提醒，不连接交易账户，不自动下单。
- 自选、Trading Plan 和持仓由用户手动维护。
- 持仓变化通过 `PositionEvent` 追加记录，不覆盖历史。
- Crypto、US Equity、A-Share 是三个独立 bounded context。
- Agent 只能编排授权 Skill 并生成 DecisionProposal，不能直接写入 Signal、Position
  或交易指令。
- Policy Gate 只有在批准 Proposal 后才能签发 DecisionTicket。
- Signal State Machine 只消费已授权 DecisionTicket，是 Signal 状态唯一写入口。
- MarketSnapshot identity 必须绑定完整输入窗口；已闭合 K 线必须满足时间真实性。
- Ticket 必须绑定授权时的 Signal 与业务上下文版本，状态机从事实源验证授权链。

## 文档入口

- 项目文档总入口：[docs/README.md](docs/README.md)
- 当前项目记忆：[docs/development/memory.md](docs/development/memory.md)
- 架构文档索引：[docs/architecture/README.md](docs/architecture/README.md)
- 系统宏观架构：[docs/architecture/system/loot-system-architecture-v0.1.md](docs/architecture/system/loot-system-architecture-v0.1.md)
- 核心契约设计：[docs/architecture/contracts/loot-contracts-v0.1.md](docs/architecture/contracts/loot-contracts-v0.1.md)
- 决策运行时与授权链路：[docs/architecture/runtime/decision-flow-v0.1.md](docs/architecture/runtime/decision-flow-v0.1.md)
- Signal State Machine：[docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md](docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md)
- 自选与持仓信号监控闭环：[docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md](docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md)
- Crypto 行情数据 Provider：[docs/architecture/market-domains/crypto-market-data-provider-v0.1.md](docs/architecture/market-domains/crypto-market-data-provider-v0.1.md)

## 本地运行

当前仅可运行示例脚本：

```bash
py main.py
```

预期输出：

```text
Hi, PyCharm
```

更完整的运行说明见 [docs/runbooks/local-run.md](docs/runbooks/local-run.md)。

当前契约测试：

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
py -3.12 -m unittest discover -s tests -p 'test_*.py'
```

## 下一步

1. 完成 REQ-0009，修复第二轮复核确认的地基不变量。
2. 定义 Crypto Golden Case 输入和预期。
3. 按 Golden Case 实现 FakeCryptoPreFilter。
4. 串联 DecisionProposal、PolicyEvaluation、DecisionTicket 和 Signal State Machine。
5. 补持久化幂等与 Outbox，再接 Agent 和 Alert。
