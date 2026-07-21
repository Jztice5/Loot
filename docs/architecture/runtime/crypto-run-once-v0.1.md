# Loot Crypto Run-Once 应用闭环设计 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Accepted |
| 版本 | 0.1 |
| 日期 | 2026-07-21 |
| 适用范围 | Crypto 单次行情分析与决策事实持久化 |
| 需求 | REQ-0013 |

## 1. 问题定义

Loot 已经具备 Crypto Provider、PreFilter、确定性 Decision Builder、Policy Gate、Signal State
Machine 和 PostgreSQL Repository，但这些组件只在测试中被分别调用。测试结束还会清理数据，
因此操作者无法通过一个正式入口运行链路，也无法在 DBX 中观察进程退出后保留的业务事实。

REQ-0013 增加薄应用层，把既有能力串起来；它不改变领域判断、授权规则和事实仓库所有权。

## 2. 目标与非目标

### 2.1 目标

- 用一个同步命令执行一次 Crypto 分析链。
- 支持稳定可演示的 `demo` 和真实只读行情的 `live` 两种模式。
- 有 Candidate 时完整经过 Analysis Repository、Policy Gate 和 Signal workflow。
- 返回可机器读取的摘要，包含运行状态、原因码和持久化事实 ID。
- 默认只使用 `loot_test`，运行完成后不清理业务事实。

### 2.2 非目标

- 不实现 scheduler、队列 consumer、常驻 worker、Alert 或 Replay。
- 不保存原始 MarketBar 和 MarketSnapshot，不新增 migration。
- 不把 Candidate 提升为独立表；本阶段只用完整 Candidate 消息计算 Inbox payload 指纹，
  Inbox 表不保存原始 payload，关键语义由 Evidence、Proposal 和 Signal 事实承接。
- 不引入 Agent/LLM，不调用 REQ-0012 Skill Runtime。
- 不访问交易账户，不下单，不触碰 `loot_dev`。

## 3. 权威调用链

```text
RunOnceCommand
  -> CryptoMarketDataProvider.fetch_recent_bars
  -> CryptoStructurePreFilter.evaluate
  -> [无 Candidate] RunOnceResult(NO_CANDIDATE)
  -> [有 Candidate] PostgresSignalWorkflow.initialize
  -> DeterministicDecisionBuilder.build
  -> PostgresAnalysisRepository.record_analysis_result
  -> CryptoPolicyGate.evaluate(PostgresAuthorizationRepository)
  -> [未批准] RunOnceResult(POLICY_NOT_APPROVED)
  -> [批准] PostgresSignalWorkflow.apply
  -> RunOnceResult(SIGNAL_TRANSITIONED)
```

Signal 初始化放在 Candidate 之后。这样 live 行情没有突破时不会创建无业务意义的 OBSERVING
投影。初始化仍由 Signal workflow 完成，应用层只提供显式命令参数。

## 4. 运行模式

### 4.1 demo

- 构造 4 根当前 UTC 时间之前已收盘的 H1 K 线。
- 前 3 根形成参考区间，最后一根 close 严格高于参考 high，稳定产生 LONG Candidate。
- 每次 CLI 调用默认生成新的 `watch_item_id`，允许重复演示且不与活跃 Signal 冲突。
- demo 只保证契约和授权链可执行，不代表真实市场判断。

### 4.2 live

- 使用 `OkxRestCryptoProvider` 读取 OKX `BTC-USDT` 最近 4 根已收盘 H1 K 线。
- 真实行情没有结构突破时返回 `NO_CANDIDATE`，不伪造方向或 Signal。
- 网络、响应和契约错误向调用方报告失败并以非零退出码结束。

## 5. 应用契约

`CryptoRunOnceCommand` 至少包含：

```text
mode = demo | live
instrument
timeframe
watch_item_id
watch_item_version
context_digest
position_id
```

`CryptoRunOnceResult` 至少包含：

```text
status
mode
reason
snapshot_id
candidate_id
direction
signal_id
proposal_id
policy_evaluation_id
decision_ticket_id
signal_state
```

结果只返回审计 ID、状态和稳定原因码；不得包含 DSN、数据库用户名、口令或完整行情 payload。

## 6. 时间、身份与幂等

- 内部时间全部使用 UTC aware datetime。
- Candidate 的 `occurred_at` 来自触发 K 线闭合时间，Policy `evaluated_at` 必须落在 Evidence
  有效期内，Signal 迁移时间不得早于当前投影。
- `setup_key` 绑定 Candidate identity 和 direction；同一输入重试命中相同 Signal 初始化事实。
- Inbox `message_id` 使用 Candidate ID，使相同 Candidate 重投返回已有 Analysis 事实。
- Policy `evaluation_request_id` 默认由 Candidate/Proposal 上下文稳定派生。
- Signal workflow 继续以 Ticket ID 和完整 payload 指纹保证重复消费安全。

## 7. 持久化与事务边界

Run-Once 复用既有三个事务边界：

1. Signal 初始化与初始化 Outbox。
2. Inbox、Evidence、Proposal、引用关系与 Proposal Outbox。
3. PolicyEvaluation、可选 Ticket 与授权 Outbox。
4. Signal 投影、Transition、Ticket consumption 与 Signal Outbox。

这些事务不会被包装成一个超大数据库事务。中途失败时已经提交的不可变事实可以用于诊断，
调用方可用相同业务身份重试；既有幂等约束负责收敛。Run-Once 本身不做删除补偿。

## 8. 安全与配置

- CLI 只从 `LOOT_TEST_DATABASE_URL` 或 `%USERPROFILE%/.loot/database.env` 加载测试库 DSN。
- 输出和异常不得回显 DSN；数据库驱动错误由现有脱敏边界处理。
- demo 和 live 都只写 `loot_test` 中现有 `loot` schema 的 10 张表。
- live 只使用 OKX public REST，不需要 API key，不接触账户能力。

## 9. 验收

- demo 稳定产生 LONG Candidate，并将 Signal 从 OBSERVING 迁移到 ARMED。
- live 无 Candidate 时数据库不出现对应 Signal、Proposal、Ticket 或 Transition。
- PostgreSQL 集成测试验证完整链路，测试只清理自身创建的数据。
- 手工 demo 不清理数据，DBX 可以按返回 ID 查询完整事实链和 Outbox 事件。
- 全量测试、compileall、PyCharm 构建/检查、context check 和代码规范审查通过。
