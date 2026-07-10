# Loot

Loot the market before it loots you.

Loot 是一个面向个人自选与手动持仓的多市场信号监控系统，目标是持续跟踪 Crypto、美股和 A 股中的关键价格结构、量价变化和信息事件，在值得关注的状态变化发生时提醒用户，减少反复看盘。

当前项目处于 Phase 0 架构基础阶段，已建立 Python 项目骨架、第一批核心 contracts 和 Signal State Machine v0.1。现有 `main.py` 仍是 PyCharm 示例脚本，下一步会围绕 FakeProvider、FakePreFilter 和 Golden Case 搭第一条可运行闭环。

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
- 核心契约设计：[docs/architecture/contracts/loot-contracts-v0.1.md](docs/architecture/contracts/loot-contracts-v0.1.md)
- Signal State Machine：[docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md](docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md)
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

当前契约测试：

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
py -3.12 -m unittest discover -s tests -p 'test_*.py'
```

## 下一步

1. 做 FakeProvider 和 FakePreFilter。
2. 用 Crypto 自选跑通 Candidate 到 Signal 的最小闭环。
3. 准备 Golden Case，验证幂等、状态迁移和提醒去重。
4. 再接 Alert Center 和 FakeNotifier。
