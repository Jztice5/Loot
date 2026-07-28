# REQ-0014 Crypto WatchItem 与监控订阅评审

## 范围

- Instrument、WatchItem、MonitoringSubscription 契约与 PostgreSQL schema。
- 创建及 ACTIVE、PAUSED、ARCHIVED 生命周期。
- Inbox/Outbox 幂等、并发身份锁、版本冲突与事务回滚。
- Run-Once 持久化监控身份接入和真实 `loot_test` 验收。

## 结论

REQ-0014 通过验收。Crypto Run-Once 已不能临时生成监控身份，只能消费数据库中 ACTIVE 的
Crypto H1 WatchItem 与 Subscription。创建和生命周期变化具有稳定命令身份、首次结果恢复、
乐观版本控制和事务级并发保护，真实数据库、CLI 与完整决策链均已验证。

## 已对齐项

- WatchItem、Subscription 和 Outbox 在同一事务提交，重复 request 返回首次投影。
- ACTIVE 自然身份和 Instrument 双重身份均有事务锁与数据库约束保护。
- PAUSED 不可运行，ARCHIVED 不可恢复，Subscription 状态和配置版本同步推进。
- Run-Once 使用数据库中的 Instrument、WatchItem version、timeframe 与 route key。
- CLI 只允许 `loot_test`，错误输出不包含 DSN 或驱动诊断。
- 失败事务不会残留 Inbox 认领；相同 request_id 修正命令后可重新执行。

## 保留风险

- `next_run_at` 当前为空，尚无到期订阅查询、租约、Run 账本和恢复 worker；这些属于 REQ-0015。
- 未发布 Outbox 尚无 dispatcher，当前事件只能由数据库查询观察。
- 原始行情输入未持久化，无法仅靠 PostgreSQL 重放本次 demo 的完整 Snapshot。
- 数据库对象 owner 仍为 `postgres`，正式环境 rollout 前需明确 migration 所有权策略。

## 复核清单

- REQ-0015 必须以 `subscription + bar close time + workflow version` 建立稳定 Run 身份。
- Worker 只能查询 ACTIVE Subscription，并在 Provider 调用前再次校验 WatchItem 和配置版本。
- 租约过期、进程中断、无 Candidate 和 Provider 短暂失败必须有不同恢复语义。
- REQ-0016 只消费 SignalEvent/Outbox，不得通过提醒链反向写 Signal。
