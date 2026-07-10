# Loot Codex Working Agreement

本文件适用于整个仓库。Codex 在分析、设计或修改 Loot 前，必须先阅读：

1. `docs/README.md`
2. `docs/development/memory.md`
3. `docs/architecture/README.md`
4. `docs/architecture/system/loot-system-architecture-v0.1.md`
5. 与任务相关的 `docs/architecture/*/*.md` 或 `docs/development/log/*.md`

## Project Definition

Loot 是面向个人自选与手动持仓的多市场信号监控系统，覆盖：

- Crypto
- US Equity
- A-Share

系统持续分析行情、量价结构与信息事件，减少用户频繁看盘。V1 只提供决策辅助和提醒，不连接交易账户，不自动下单。

## Non-Negotiable Architecture Rules

1. 三个市场是独立 bounded context，分别拥有数据、信息、规则、Agent、Skills、Policy 和 Signal State Machine。
2. 市场路由必须是确定性的，不能交给大模型决定。
3. Agent 只能选择分析路径和编排已授权 Skills，不能直接改变 Signal 状态、修改持仓或发送交易指令。
4. Skill 必须具有强类型输入输出、版本、市场范围、超时和权限声明。
5. Policy Gate 不可绕过；Signal State Machine 是信号状态的唯一写入入口。
6. 自选和持仓由用户手动维护。持仓变化必须追加 PositionEvent，不能通过覆盖历史掩盖操作过程。
7. PostgreSQL 是业务状态事实源；Redis 只承担缓存、锁和事件流。
8. 所有消费者按至少一次投递设计，必须实现幂等。
9. 内部时间统一使用 UTC，展示层转换为市场或用户时区。
10. V1 不实现自动交易、券商同步、全市场扫描或高频交易。

## Module Boundaries

- `src/loot/domains/crypto`、`us_equity`、`a_share` 之间禁止直接依赖。
- 跨领域只能依赖 `contracts`、`shared` 或平台公开接口。
- `shared/quantitative` 只能包含无市场业务语义的纯函数。
- 市场 Session、成交量基准、复权、信息链路和可操作性规则必须留在对应市场领域。
- Provider 负责外部访问；Skill 不允许随意发起未声明的网络请求。

## Required Change Workflow

Codex 实现功能前必须：

1. 确认目标用户场景和非目标。
2. 列出涉及的领域、模块、契约、表、事件和状态机。
3. 阅读或创建对应组件级、功能级或过程设计文档。
4. 先定义或修改契约，再实现生产者和消费者。
5. 为事件消费、状态转换和人工 PositionEvent 增加幂等处理。
6. 为市场规则添加单元测试，为跨模块闭环添加集成或 Replay 测试。
7. 如果实现与文档不同，同一变更中更新设计文档。

## Context Closeout

每次完成实质设计或实现后，必须检查上下文是否需要收尾：

- 稳定边界、契约、状态机或非目标变化时，更新 `docs/architecture/`。
- 当前状态、验证命令、未完成事项或下一步变化时，更新 `docs/development/memory.md`。
- 出现有保留价值的推理、debug 或放弃方案时，写入 `docs/development/log/`。
- 形成阶段结论、风险判断或复核清单时，写入 `docs/reviews/`。
- 出现可重复操作命令时，写入 `docs/runbooks/`。
- 未来 Codex 必须遵守的新硬约束，提升到本文件。

## Definition of Done

一个跨模块功能只有在以下条件全部满足时才算完成：

- API、事件、数据表和状态迁移一致。
- Agent 无法绕过 Skill、Policy Gate 和 Signal State Machine。
- 重试不会产生重复状态或重复提醒。
- 核心路径具有可追踪的 correlation_id、skill_run_id 和 input_snapshot_id。
- 至少覆盖成功、拒绝、重复投递、依赖失败和恢复路径。
- 文档、迁移、测试和实现保持同步。
- 上下文入口、memory、相关设计文档和 runbook 没有过期链接或明显矛盾。
