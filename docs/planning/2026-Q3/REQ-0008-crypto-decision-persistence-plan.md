# REQ-0008 Crypto 决策链路持久化实施计划

## 目标

把 REQ-0007 的单进程内存授权链升级为 PostgreSQL 事实源，使重复投递、进程重启、
并发迁移和 Outbox 发布失败都能从数据库恢复。

## 非目标

- 不接 Agent、Alert 渠道或 Redis Streams。
- 不实现 US Equity 或 A-Share 表和领域规则。
- 不在本需求实现 Outbox dispatcher 的生产调度，只固定待发布事实和认领字段。

## 实施顺序

1. 固定 Schema、约束、事务和失败语义。
2. 增加 SQLAlchemy、psycopg 基础设施及首个可由 DBX 直接执行的版本化 SQL migration。
3. 实现 Evidence/Proposal 与 Inbox/Outbox 原子写入。
4. 实现 PolicyEvaluation/Ticket/Outbox 原子写入和可重评语义。
5. 实现 Signal 初始化、Ticket 消费、Transition、SignalEvent Outbox 原子事务。
6. 增加重启重复、冲突 payload、乐观锁、单活跃代和事务回滚测试。
7. 通过 DBX 在 `loot_test` 验证 migration，在 `loot_dev` 应用同一版本。

## 验收映射

| 验收点 | 证据 |
|---|---|
| 同一 Inbox 消息重复消费不重复写业务事实 | PostgreSQL 集成测试与唯一约束 |
| DEFERRED 可追加评估，同一请求幂等 | Evaluation 唯一约束与 Repository 测试 |
| 同一 Proposal 最多一张 Ticket | `decision_tickets.proposal_id` 唯一约束 |
| 同一监控身份最多一个活跃 Signal generation | partial unique index |
| Ticket 消费、Signal 更新、Transition、Outbox 同事务 | workflow 回滚与重启测试 |
| 相同 Ticket ID 不同 payload 被拒绝 | consumption fingerprint 冲突测试 |
| 发布失败可恢复 | Outbox unpublished 查询和重试字段测试 |

## 数据库执行约束

- DDL 和数据库事实验证优先使用 DBX。
- migration 由 `loot_migrator` 执行，应用运行使用 `loot_app`。
- 密码只通过本机环境变量或 DBX 连接保存，不写入仓库、日志或测试 fixture。
