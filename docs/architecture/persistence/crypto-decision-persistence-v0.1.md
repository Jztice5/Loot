# Loot Crypto 决策链路持久化设计 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Accepted，实施中 |
| 版本 | 0.1 |
| 日期 | 2026-07-16 |
| 需求 | REQ-0008 |
| 数据库 | PostgreSQL 18，schema `loot` |
| 适用范围 | Crypto First Vertical Slice 的授权与 Signal 事实 |

## 1. 目标与边界

本设计把 REQ-0007 的内存 Evidence、Proposal、PolicyEvaluation、DecisionTicket、
Signal 和幂等账本迁移到 PostgreSQL。PostgreSQL 是唯一业务事实源；Redis、进程内缓存
和消息中间件都不能代替数据库唯一约束或事务。

不在本设计实现 Agent、Alert dispatcher、Redis Streams、自动交易或其他市场业务表。

## 2. 表与职责

| 表 | 职责 | 核心唯一约束 |
|---|---|---|
| `inbox_messages` | 至少一次投递的消费者幂等入口 | `(consumer_name, message_id)` |
| `evidence_sets` | 方向性分析证据事实 | `id`、`dedupe_key` |
| `decision_proposals` | Policy 前不可变提案 | `id`、`dedupe_key` |
| `decision_proposal_evidence` | Proposal 到 Evidence 的有序引用 | `(proposal_id, position)`、Evidence 唯一引用 |
| `policy_evaluations` | 只追加 Policy 评估 | `evaluation_request_id`；Proposal/Policy/Context |
| `decision_tickets` | APPROVED 后唯一授权 | `proposal_id`、`policy_evaluation_id` |
| `signal_instances` | Signal 当前及历史 generation | 监控身份/generation；单活跃代 partial index |
| `decision_ticket_consumptions` | Ticket 首次消费结果与 payload 指纹 | `decision_ticket_id` |
| `signal_transitions` | 已发生的状态迁移事实 | `(signal_id, decision_ticket_id)`、`event_id` |
| `outbox_events` | 待发布领域事件 | `event_id` |

所有 UUID 由应用生成；所有时间使用 `TIMESTAMPTZ`；结构化 payload 使用 `JSONB`；
金额和质量分使用 `NUMERIC`。状态和方向先用 `TEXT + CHECK`，避免 PostgreSQL enum
迁移阻塞协议演进。

## 3. 不可变事实与摘要

- Evidence、Proposal、Evaluation、Ticket、Transition 和 Outbox 写入后不可更新业务
  payload；只允许 Outbox 发布状态和 Inbox 处理状态更新。
- 每个不可变对象保存 canonical payload fingerprint。相同 ID/dedupe identity 且指纹一致
  视为重试；指纹不同视为冲突。
- Proposal 保存 `proposal_digest`；Evaluation 和 Ticket 必须引用相同摘要。
- Ticket consumption 保存完整 Ticket fingerprint 和首次 `SignalTransitionResult` JSON，
  进程重启后的重复消费返回首次结果。

## 4. Signal generation

Signal 监控身份为：

```text
(watch_item_id, market, instrument_id, timeframe, signal_type, direction)
```

规则：

- `generation` 从 1 开始，`setup_key` 标识该身份的一轮结构。
- 相同身份、generation 唯一；相同身份、setup_key 幂等。
- `INVALIDATED`、`RESOLVED`、`EXPIRED` 为终态。
- partial unique index 约束同一身份最多一个非终态实例。
- 初始化事务先获取基于监控身份的 PostgreSQL transaction advisory lock，再读取最新
  generation，避免“尚无行可锁”时并发创建两个第一代 Signal。

## 5. 原子事务

### 5.1 Analysis 事务

```text
Inbox claim
+ EvidenceSet
+ DecisionProposal
+ ProposalEvidence refs
+ Proposal Outbox
+ Inbox processed
```

同一 Inbox 消息重复到达时返回首次 Proposal；payload fingerprint 不同则冲突。

### 5.2 Policy 事务

```text
验证/写入 Proposal
+ PolicyEvaluation
+ [APPROVED] DecisionTicket
+ Evaluation/Ticket Outbox
```

同一 evaluation_request 幂等；相同 Proposal、Policy 版本和 evaluation context 只有一个
评估事实。DEFERRED 新 request/context 可以追加 attempt；REJECTED/APPROVED 终结 Proposal。

### 5.3 Signal 初始化事务

```text
监控身份 advisory lock
+ 查询最新 generation
+ 幂等插入 OBSERVING SignalInstance
+ SignalInitialized Outbox
```

### 5.4 Signal 迁移事务

```text
Ticket advisory lock
+ 查询已有 consumption
+ SELECT Signal FOR UPDATE
+ 加载并验证 Proposal/Evaluation/Ticket
+ 校验 expected_signal_version/context_digest
+ 更新 Signal version
+ SignalTransition
+ DecisionTicketConsumption(result payload)
+ SignalEvent Outbox
```

任一步失败时整个事务回滚，不能留下“Ticket 已消费但 Signal 未更新”或“Signal 已更新但
事件未进入 Outbox”的中间状态。

## 6. 乐观锁与冲突

- Signal 更新使用 `WHERE id = :id AND version = :expected_version`，影响行数不是 1 时抛出
  `SignalVersionConflictError`。
- Ticket advisory lock 让相同 Ticket 的并发重试先后读取 consumption；唯一约束仍是最终
  防线。
- SQLSTATE `23505` 不能统一解释为幂等；Repository 必须加载已有事实并比较 fingerprint。
- 数据库断连、序列化失败和死锁允许事务级重试；业务版本冲突不能盲目重试旧 Proposal。

## 7. Outbox 恢复

Outbox 保存 `available_at`、`published_at`、`attempt_count`、`last_error` 和锁定时间。认领器
后续使用 `FOR UPDATE SKIP LOCKED` 批量领取；发布成功只更新发布状态，不删除历史事件。
本需求只实现表、写入和未发布查询，不实现真实消息中间件 dispatcher。

## 8. 安全与权限

- Alembic 使用 `loot_migrator`；应用 Repository 使用 `loot_app`。
- Repository SQL 显式使用 `loot` schema，不依赖超级用户 search_path。
- DSN 只从环境变量读取，异常和日志不得输出密码。
- 测试只使用 `loot_test`，禁止清理或 truncate `loot_dev`。

## 9. 验证

- migration upgrade/downgrade 在空 `loot_test` schema 可重复执行。
- Repository 覆盖成功、重复、冲突 payload 和事务回滚。
- Workflow 覆盖进程重建后的 Ticket 重复、并发 Signal 初始化、乐观锁冲突和 Outbox 恢复。
- DBX 验证表、索引、约束、角色权限和 UTC 时间类型。
