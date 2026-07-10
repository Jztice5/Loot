# 开发过程记忆

> 项目级开发记忆，只保留当前状态、关键历史索引和下一步。
> 具体功能点的过程记录放在 [log/](log/README.md)。

## 当前状态

- 项目定位：面向个人自选与手动持仓的多市场信号监控系统。
- 当前阶段：Phase 0 架构基础阶段，已建立核心 contracts、Signal State Machine v0.1 和 Crypto 行情数据 Provider v0.1。
- 当前代码入口：`main.py` 仍是 PyCharm 示例脚本；核心契约代码在 `src/loot/contracts`，状态机代码在 `src/loot/signals`，Crypto 行情代码在 `src/loot/domains/crypto`。
- 当前文档入口：`docs/README.md`。
- 当前宏观设计：`docs/architecture/system/loot-system-architecture-v0.1.md`。
- 当前契约设计：`docs/architecture/contracts/loot-contracts-v0.1.md`。
- 当前状态机设计：`docs/architecture/signal-state-machine/loot-signal-state-machine-v0.1.md`。
- 当前 Crypto 行情设计：`docs/architecture/market-domains/crypto-market-data-provider-v0.1.md`。
- 当前闭环设计：`docs/architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md`。
- 当前上下文维护机制：`docs/README.md` 作为入口，`development/memory.md` 记录状态，`development/log` 记录过程，`reviews` 记录阶段结论，`runbooks` 记录可执行步骤。

## 设计主线

```text
WatchItem / TradingPlan / PositionEvent
-> Market Router
-> Market Domain PreFilter
-> Market Agent
-> Skill Runtime
-> Policy Gate
-> Signal State Machine
-> Alert Center
-> User Action
-> PositionEvent
```

## 关键结论

- 三个市场是独立 bounded context，不抽成一套通用市场规则。
- Agent 只做分析路径选择和 Skill 编排，不直接写 Signal、Position 或交易指令。
- Policy Gate 和 Signal State Machine 是状态变化的强制入口。
- PositionEvent 是持仓历史事实，Position 是当前投影。
- V1 不接交易账户、不自动下单、不做全市场扫描。
- 第一条可运行闭环应优先使用 FakeProvider 和 Golden Case 验证幂等、状态迁移和提醒去重。
- 上下文维护遵循“稳定设计进 architecture、当前状态进 memory、过程推理进 log、可执行步骤进 runbook、阶段结论进 review”。
- 已创建全局 Codex skill `vibe-context-manager`，可复用到其他长期 vibe coding 项目。
- 第一批 contracts 使用 Pydantic v2 不可变模型，禁止额外字段，并要求跨模块时间为 timezone-aware UTC。
- Signal State Machine v0.1 使用固定合法迁移表和内存幂等账本；同一 `DecisionTicket` 重复消费不会重复生成 `SignalEvent`。
- Crypto 行情数据 Provider v0.1 已接入：`FakeCryptoProvider` 用于可复现测试，`OkxRestCryptoProvider` 只读访问 OKX public REST K 线。
- 行情数据只进入 `MarketBar` 和 `MarketSnapshot`，不能直接写 Candidate、Signal、Position 或交易指令。
- 已将 `code-standards` Java 版业务注释思路迁移到 Loot Python 代码：
  核心契约 docstring 需要标明业务描述、场景、原因、调用链和规则。
- 当前测试使用标准库 `unittest`，避免 Phase 0 依赖 pytest 安装。

## 历史索引

| 日期 | 主题 | 摘要 | 详情 |
| --- | --- | --- | --- |
| 2026-07-10 | 初始设计分层 | 参考智能客服项目文档体系，建立 Loot 的 architecture / development / planning / reviews / runbooks 分层 | [设计分层校对备忘录](../reviews/loot-design-layering-review-2026-07-10.md) |
| 2026-07-10 | 上下文维护机制优化 | 补齐过程日志、上下文健康检查 runbook 和 AGENTS 收尾归档规则 | [过程记录](log/2026-07-10-context-management.md) |
| 2026-07-10 | 核心契约骨架 | 建立 pyproject、src/loot/contracts 和第一批契约测试 | [过程记录](log/2026-07-10-contracts-foundation.md) |
| 2026-07-10 | Signal State Machine v0.1 | 建立状态机运行时、合法迁移表和内存幂等测试 | [过程记录](log/2026-07-10-signal-state-machine.md) |
| 2026-07-10 | Crypto 行情 Provider v0.1 | 定义 MarketBar/MarketSnapshot，接入 FakeCryptoProvider 和 OKX public REST K 线 | [过程记录](log/2026-07-10-crypto-market-data-provider.md) |

## 已验证

- `py main.py` 可运行并输出 `Hi, PyCharm`。
- 当前文档已按系统级和闭环级分层。
- `git diff --check` 已用于格式检查。
- `py -3.12 -m compileall src tests`：通过。
- `$env:PYTHONPATH='D:\my-projects\Loot\src'; py -3.12 -m unittest discover -s tests -p 'test_*.py'`：26 tests OK。
- OKX public REST smoke：通过，返回 2 根 BTC-USDT 1H K 线。

## 未完成

- Persistence 和 migrations。
- FakeCryptoPreFilter 和第一批 Golden Case。
- Skill Manifest、SkillRun 和 Guard 输出契约。

## 下一步

优先级建议：

1. 做 FakeCryptoPreFilter，从 `MarketSnapshot` 产生第一条 `CandidateEvent`。
2. 用 Crypto 自选跑通一条 Candidate 到 Signal 的最小闭环。
3. 补第一批 Golden Case，验证重复行情、重复候选和重复 DecisionTicket 不重复迁移。
4. 设计持久化层中的 DecisionTicket 消费标记、SignalTransition 和 outbox。
5. 再开始 Skill Runtime 和 Agent 接入。

日常计划记录放在 [../planning/开发计划.md](../planning/开发计划.md)。
