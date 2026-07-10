# Loot

Loot the market before it loots you.

Loot 是一个面向个人自选与手动持仓的多市场信号监控系统，目标是持续跟踪 Crypto、美股和 A 股中的关键价格结构、量价变化和信息事件，在值得关注的状态变化发生时提醒用户，减少反复看盘。

当前项目处于架构设计和上下文分层阶段，生产代码尚未启动。现有 `main.py` 仍是 PyCharm 示例脚本，后续会先建立 Python 项目骨架和核心 contracts，再进入第一条可运行闭环。

## 核心边界

- V1 只做决策辅助和提醒，不连接交易账户，不自动下单。
- 自选、Trading Plan 和持仓由用户手动维护。
- 持仓变化通过 `PositionEvent` 追加记录，不覆盖历史。
- Crypto、US Equity、A-Share 是三个独立 bounded context。
- Agent 只能编排授权 Skill，不能直接写入 Signal、Position 或交易指令。
- Signal 状态变化必须经过 Policy Gate 和 Signal State Machine。

## 文档入口

- 项目文档总入口：[docs/README.md](docs/README.md)
- 当前项目记忆：[docs/development/memory.md](docs/development/memory.md)
- 架构文档索引：[docs/architecture/README.md](docs/architecture/README.md)
- 系统宏观架构：[docs/architecture/system/loot-system-architecture-v0.1.md](docs/architecture/system/loot-system-architecture-v0.1.md)
- 自选与持仓信号监控闭环：[docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md](docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md)

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

## 下一步

1. 建立 Python 项目骨架：`pyproject.toml`、`src/loot`、`tests`。
2. 定义核心 contracts：Market、InstrumentType、Timeframe、SignalState、EventEnvelope。
3. 用 FakeProvider 跑通第一条 Crypto 自选到 Signal 到 Alert 的最小闭环。
4. 准备 Golden Case，验证幂等、状态迁移和提醒去重。
