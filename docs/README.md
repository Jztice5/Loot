# 项目文档索引

## 先看哪里

- 当前项目状态：[development/memory.md](development/memory.md)
- 设计分层索引：[architecture/README.md](architecture/README.md)
- 当前季度规划：[planning/2026-Q3/规划总览-2026-Q3.md](planning/2026-Q3/规划总览-2026-Q3.md)
- 本地运行说明：[runbooks/local-run.md](runbooks/local-run.md)

## 时间上下文模型

- 过去式上下文：已经发生的过程、结果和证据，进入 development log、reviews 和已完成或归档需求。
- 现在进行时上下文：当前执行、阻塞、恢复点和验证基线在 `development/memory.md` 维护，
  具体需求状态仍以 planning 原条目为准。
- 未来规划上下文：尚未发生的需求、依赖、队列和验收标准，进入 planning 并使用
  Planned/Deferred 状态。
- architecture、AGENTS 和 runbooks 是跨时间稳定上下文，从历史与当前工作中提炼并约束未来。

权威定义：[Loot 时间上下文模型 V0.1](architecture/context/temporal-context-model-v0.1.md)。

## 架构设计

- 系统宏观架构：[architecture/system/loot-system-architecture-v0.1.md](architecture/system/loot-system-architecture-v0.1.md)
- 核心契约设计：[architecture/contracts/loot-contracts-v0.1.md](architecture/contracts/loot-contracts-v0.1.md)
- 决策运行时与授权链路：[architecture/runtime/decision-flow-v0.1.md](architecture/runtime/decision-flow-v0.1.md)
- Skill Runtime：[architecture/runtime/skill-runtime-v0.1.md](architecture/runtime/skill-runtime-v0.1.md)
- Runtime Console：[architecture/runtime/runtime-console-v0.1.md](architecture/runtime/runtime-console-v0.1.md)
- 智能决策闭环机制：[architecture/runtime/intelligent-decision-loop-v0.1.md](architecture/runtime/intelligent-decision-loop-v0.1.md)
- 自选与持仓信号监控闭环：[architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md](architecture/signal-monitoring/signal-monitoring-loop-design-v0.1.md)
- Signal State Machine：[architecture/signal-state-machine/loot-signal-state-machine-v0.1.md](architecture/signal-state-machine/loot-signal-state-machine-v0.1.md)
- Crypto 行情数据 Provider：[architecture/market-domains/crypto-market-data-provider-v0.1.md](architecture/market-domains/crypto-market-data-provider-v0.1.md)
- Crypto Structure PreFilter：[architecture/market-domains/crypto-prefilter-v0.1.md](architecture/market-domains/crypto-prefilter-v0.1.md)
- Crypto Golden Cases：[architecture/testing/crypto-golden-cases-v0.1.md](architecture/testing/crypto-golden-cases-v0.1.md)
- Crypto 决策链路持久化：[architecture/persistence/crypto-decision-persistence-v0.1.md](architecture/persistence/crypto-decision-persistence-v0.1.md)
- 时间上下文模型：[architecture/context/temporal-context-model-v0.1.md](architecture/context/temporal-context-model-v0.1.md)

## 开发过程

- 开发过程索引：[development/log/README.md](development/log/README.md)
- 2026-Q3 开发过程总览：[development/log/2026-Q3/开发过程总览-2026-Q3.md](development/log/2026-Q3/开发过程总览-2026-Q3.md)
- 过程记录模板：[development/log/TEMPLATE.md](development/log/TEMPLATE.md)

## 评审记录

- 评审跨季度索引：[reviews/README.md](reviews/README.md)
- 2026-Q3 评审记录总览：[reviews/2026-Q3/评审记录总览-2026-Q3.md](reviews/2026-Q3/评审记录总览-2026-Q3.md)

## Runbooks

- 本地运行说明：[runbooks/local-run.md](runbooks/local-run.md)
- PostgreSQL SQL Migration：[runbooks/postgresql-sql-migrations.md](runbooks/postgresql-sql-migrations.md)
- 上下文健康检查：[runbooks/context-health-check.md](runbooks/context-health-check.md)
- 同步项目 Skills：[runbooks/sync-project-skills.md](runbooks/sync-project-skills.md)

## 项目 Skills

- Skills 索引：[skills/README.md](skills/README.md)
- Vibe Context Manager：[skills/vibe-context-manager/SKILL.md](skills/vibe-context-manager/SKILL.md)

## 需求与计划

- 规划跨季度索引：[planning/README.md](planning/README.md)
- 规划总览 2026-Q3：[planning/2026-Q3/规划总览-2026-Q3.md](planning/2026-Q3/规划总览-2026-Q3.md)
- 需求管理 2026-Q3：[planning/2026-Q3/需求管理-2026-Q3.md](planning/2026-Q3/需求管理-2026-Q3.md)

## 目录分工

```text
docs/
  architecture/   稳定架构设计：系统级、组件级、功能闭环级设计
  development/    当前 memory 固定；过程日志按 yyyy-Qn 归档
  planning/       需求队列和季度总览按 yyyy-Qn 归档并显式命名
  reviews/        设计评审和阶段结论按 yyyy-Qn 归档
  runbooks/       本地运行、测试、排障手册
  skills/         可随 Git 多端同步的项目级 Codex skills
```

## 分层原则

- `architecture/system` 只回答系统为什么这样分层、边界在哪里、P1 不做什么。
- `architecture/<component>` 回答某个闭环或组件如何运行、契约是什么、状态如何变化。
- `development/memory.md` 只记录当前执行、阻塞、恢复点和验证基线。
- `development/log` 记录过去的判断、证据、改动和验证，不发布当前任务指令。
- `planning` 中的需求管理是需求状态、依赖和计划队列的唯一事实源。
- `reviews` 记录阶段校对结论，避免设计债和实现债散落在聊天里。
- `runbooks` 记录可复用操作步骤，避免每次从设计文档里翻命令。
- `skills` 保存项目权威 skill，设备级 `$CODEX_HOME/skills` 只是安装镜像。
- 时间型资料进入 `yyyy-Qn/`；季度总览和需求管理文件名必须包含季度标记。

## 上下文维护规则

- 临时推理和调试过程进入 `development/log`；其中的遗留判断必须标成历史快照。
- 当前执行状态和恢复点进入 `development/memory.md`。
- 需求状态、全局计划队列和下一项需求进入 `planning` 的需求管理。
- 稳定边界、契约和状态机进入 `architecture`。
- 可重复命令和检查步骤进入 `runbooks`。
- 阶段性判断和风险清单进入 `reviews`。
