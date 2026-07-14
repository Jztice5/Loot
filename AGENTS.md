# Loot Codex Working Agreement

本文件适用于整个仓库。Codex 在分析、设计或修改 Loot 前，必须先阅读：

1. `docs/README.md`
2. `docs/development/memory.md`
3. `docs/architecture/README.md`
4. 与任务直接相关的 `docs/architecture/*/*.md` 或
   `docs/development/log/<yyyy-Qn>/*.md`

只有涉及跨市场边界、系统分层、全局可靠性或不可变架构规则时，才需要完整阅读
`docs/architecture/system/loot-system-architecture-v0.1.md`。其他任务以本文件中的硬约束
和相关组件设计为准，避免无差别加载全部架构上下文。

涉及项目上下文整理、季度归档或文档分层时，还必须阅读：

5. `docs/skills/vibe-context-manager/SKILL.md`

## Context Source of Truth

- 根 `README.md` 只保留稳定介绍和入口，不复制动态需求状态或计划队列。
- 当前执行、阻塞、恢复点和验证基线以 `docs/development/memory.md` 为准。
- 需求状态、依赖、验收标准和计划队列以当前季度 `需求管理-yyyy-Qn.md` 为准。
- development log 是过去式证据；其中的遗留判断即使仍未完成，也不是当前计划指令。
- 历史验证必须保留日期和环境；不得把旧设备上的通过结果表述为当前机器已复验。

## Temporal Context Model

- 过去式上下文记录已经发生的过程、结果和证据，权威载体是 development log、review 和
  已完成或归档需求；归档后不覆盖改写业务结论。
- 现在进行时上下文记录当前真实状态、焦点、阻塞和本机验证；项目级快照入口是
  `docs/development/memory.md`，具体需求状态仍由 planning 原条目负责，Git 与 runtime
  状态必须实时检查。
- 未来规划上下文记录尚未发生的需求、顺序和验收标准，权威载体是当前季度 planning；
  Planned/Deferred 项不能表述为已经实现或验证。
- architecture、AGENTS 和 runbooks 是跨时间稳定上下文，不表达任务完成状态。
- 任务开始时执行 `未来规划 -> 现在进行时`；完成、取消或替代时执行
  `现在进行时 -> 过去式`，并把可复用结论晋升到稳定层。

详细规则见 `docs/architecture/context/temporal-context-model-v0.1.md`。

## Project Skill Source

- `docs/skills/vibe-context-manager/SKILL.md` 是 Loot 的权威 skill 副本。
- `$CODEX_HOME/skills/vibe-context-manager` 只是设备级安装镜像。
- skill 变更先修改项目副本，再按 `docs/runbooks/sync-project-skills.md` 同步本机。
- 禁止多台设备分别维护不同的本机版本而不回写项目副本。

## Project Definition

Loot 是面向个人自选与手动持仓的多市场信号监控系统，覆盖：

- Crypto
- US Equity
- A-Share

系统持续分析行情、量价结构与信息事件，减少用户频繁看盘。V1 只提供决策辅助和提醒，不连接交易账户，不自动下单。

## Non-Negotiable Architecture Rules

1. 三个市场是独立 bounded context，分别拥有数据、信息、规则、Agent、Skills、Policy 和 Signal State Machine。
2. 市场路由必须是确定性的，不能交给大模型决定。
3. Agent 只能选择分析路径、编排已授权 Skills 并生成 DecisionProposal，不能直接创建
   DecisionTicket、改变 Signal 状态、修改持仓或发送交易指令。
4. Skill 必须具有强类型输入输出、版本、市场范围、超时和权限声明。
5. Policy Gate 不可绕过；它必须记录 PolicyEvaluation，只有批准时才能签发
   DecisionTicket；Signal State Machine 负责初始 OBSERVING Signal 的幂等创建，并且只
   消费已授权 Ticket 执行后续迁移，是信号状态的唯一写入入口。
6. 自选和持仓由用户手动维护。持仓变化必须追加 PositionEvent，不能通过覆盖历史掩盖操作过程。
7. PostgreSQL 是业务状态事实源；Redis 只承担缓存、锁和事件流。
8. 所有消费者按至少一次投递设计，必须实现幂等。
9. 内部时间统一使用 UTC，展示层转换为市场或用户时区。
10. V1 不实现自动交易、券商同步、全市场扫描或高频交易。
11. MarketSnapshot identity 必须绑定完整有序输入窗口内容；不同窗口、历史修正或闭合
    状态变化不得复用 snapshot_id。
12. `is_closed=True` 的 MarketBar 必须满足 `received_at >= closed_at`，PreFilter 不得
    消费时间上尚未闭合的 K 线。
13. Signal State Machine 必须通过事实仓库端口验证 APPROVED PolicyEvaluation、
    proposal_digest、Ticket 有效期和业务上下文版本；生产实现以 PostgreSQL 为事实源，
    Phase 0 测试可用内存适配器，但不能只信任调用方构造的 Ticket。
14. Signal 投影更新必须重新运行完整契约校验，禁止用跳过 validator 的局部复制写入
    事实状态；相同 Ticket ID 但 payload 不同必须按冲突拒绝。
15. 初始 Signal 的 latest_decision_ticket_id 为空；终态后以新 generation 创建下一轮
    SignalInstance，禁止重置或覆盖旧实例。

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
8. 涉及 Policy 或 Signal 迁移时，显式列出输入快照、Signal、WatchItem、TradingPlan
   和 Position 的版本绑定与过期处理。

## Context Closeout

每次完成实质设计或实现后，必须检查上下文是否需要收尾：

- 稳定边界、契约、状态机或非目标变化时，更新 `docs/architecture/`。
- 当前执行、阻塞、恢复点或验证基线变化时，更新 `docs/development/memory.md`。
- 需求状态、依赖或计划队列变化时，更新当前季度 `需求管理-yyyy-Qn.md`。
- 出现有保留价值的推理、debug 或放弃方案时，写入
  `docs/development/log/<yyyy-Qn>/`。
- 形成阶段结论、风险判断或复核清单时，写入 `docs/reviews/<yyyy-Qn>/`。
- 出现可重复操作命令时，写入 `docs/runbooks/`。
- 未来 Codex 必须遵守的新硬约束，提升到本文件。
- 完成收尾后在 macOS/Linux 运行 `make context-check`，Windows 运行
  `.venv\Scripts\python.exe scripts\check_context.py`；检查失败时不能宣称完成。

## Quarterly Document Rules

1. 时间型资料按事件发生日期进入 `yyyy-Qn/`，包括 development log、review 和 planning。
2. 季度总览文件必须显式包含季度：
   - `开发过程总览-yyyy-Qn.md`
   - `评审记录总览-yyyy-Qn.md`
   - `规划总览-yyyy-Qn.md`
3. 需求管理必须命名为 `需求管理-yyyy-Qn.md`，并独占需求状态和计划队列。
4. 各时间型目录根 `README.md` 只做跨季度导航，不复制季度内容。
5. architecture、memory 和 runbook 不按季度拆分；它们按稳定职责和主题维护。
6. 跨季度未完成需求必须在新季度文档中标注来源，旧季度业务结论不覆盖改写。
7. 不维护季度流水式开发计划；复杂需求需要实施计划时，创建与 REQ 绑定的专题计划。

## Definition of Done

一个跨模块功能只有在以下条件全部满足时才算完成：

- API、事件、数据表和状态迁移一致。
- Agent 无法绕过 Skill、Policy Gate 和 Signal State Machine。
- 重试不会产生重复状态或重复提醒。
- 核心路径具有可追踪的 correlation_id、input_snapshot_id、skill_run_id、
  decision_proposal_id、policy_evaluation_id 和 decision_ticket_id。
- 至少覆盖成功、拒绝、重复投递、依赖失败和恢复路径。
- 文档、迁移、测试和实现保持同步。
- 上下文入口、memory、相关设计文档和 runbook 没有过期链接或明显矛盾。
- 对应平台的 context check 通过，且当前验证记录包含实际运行环境和命令。
