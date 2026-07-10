# 开发过程记忆

> 项目级开发记忆，只保留当前状态、关键历史索引和下一步。
> 具体功能点的过程记录放在 [log/](log/README.md)。

## 当前状态

- 项目定位：面向个人自选与手动持仓的多市场信号监控系统。
- 当前阶段：架构设计和文档分层阶段，生产代码尚未启动。
- 当前代码入口：`main.py` 仍是 PyCharm 示例脚本。
- 当前文档入口：`docs/README.md`。
- 当前宏观设计：`docs/architecture/system/loot-system-architecture-v0.1.md`。
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

## 历史索引

| 日期 | 主题 | 摘要 | 详情 |
| --- | --- | --- | --- |
| 2026-07-10 | 初始设计分层 | 参考智能客服项目文档体系，建立 Loot 的 architecture / development / planning / reviews / runbooks 分层 | [设计分层校对备忘录](../reviews/loot-design-layering-review-2026-07-10.md) |
| 2026-07-10 | 上下文维护机制优化 | 补齐过程日志、上下文健康检查 runbook 和 AGENTS 收尾归档规则 | [过程记录](log/2026-07-10-context-management.md) |

## 已验证

- `py main.py` 可运行并输出 `Hi, PyCharm`。
- 当前文档已按系统级和闭环级分层。
- `git diff --cached --check` 已用于文档格式检查。

## 未完成

- Python 项目骨架：`pyproject.toml`、`src/loot`、`tests`。
- 核心 contracts：Market、InstrumentType、Timeframe、SignalState、EventEnvelope。
- Persistence 和 migrations。
- Signal State Machine 最小实现。
- FakeProvider、FakePreFilter 和第一批 Golden Case。

## 下一步

优先级建议：

1. 建立 Python 项目骨架和测试入口。
2. 先落 `src/loot/contracts`，定义不可反复摇摆的核心契约。
3. 为 contracts 增加组件级设计文档，明确枚举、事件信封和核心数据结构。
4. 用 FakeProvider 跑通一条 Crypto 自选到 Signal 到 Alert 的最小闭环。
5. 补三市场 Golden Case，验证重复事件不重复迁移和不重复提醒。
6. 再开始 Skill Runtime 和 Agent 接入。

日常计划记录放在 [../planning/开发计划.md](../planning/开发计划.md)。
