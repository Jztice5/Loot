# REQ-0013 Crypto Run-Once 评审

## 范围

- demo/live 行情入口与无候选提前退出。
- Candidate 到 Signal 的应用编排、授权边界和持久化事实。
- CLI 测试库保护、脱敏输出、单元测试和 PostgreSQL 集成验收。

## 结论

REQ-0013 通过最小闭环验收。项目已经可以通过正式 CLI 运行一次确定性 demo 或 OKX live
分析；有 Candidate 时完整经过 Analysis Repository、Policy Gate 和 Signal workflow，进程
退出后事实仍可在 DBX 查询。应用层没有获得直接创建 Ticket 或更新 Signal 表的权限。

## 已对齐项

- demo 稳定产生 LONG Candidate，live 无 Candidate 时不创建 Signal。
- Signal 初始化、Analysis、Policy 和 Signal 迁移继续使用既有事务与幂等约束。
- 只有 APPROVED PolicyEvaluation 对应 Ticket，实际迁移为 OBSERVING 到 ARMED。
- CLI 只允许 `loot_test`，不输出 DSN、口令或驱动诊断。
- 真实数据库验收覆盖现有 10 张表，测试清理与手工保留数据语义分离。

## 保留风险

- MarketBar、MarketSnapshot 和 Candidate payload 尚未持久化，当前链路适合运行验收，但还不能
  从 PostgreSQL 独立重放原始行情输入。
- 四个事务之间没有 Run 账本或恢复 worker；进程在中间阶段退出时可能留下已提交但未完成的
  OBSERVING/Proposal 事实，需要后续按业务身份恢复。
- live 仍是单标的同步 REST 调用，没有调度、批量扫描、速率限制治理或 Provider 熔断。
- SignalEvent 已进入 Outbox，但 Alert dispatcher 和用户通知尚未实现。

## 复核清单

- 设计 MarketSnapshot 留存前先确认回放周期、数据量、修正策略和冷热分层。
- 实现常驻 worker 前增加 Run 账本、阶段恢复、重试预算和并发监控身份锁语义。
- Alert 需求只消费 SignalEvent/Outbox，不允许反向修改 Signal。
- Replay 需求复用 Golden Case 和完整快照身份，不从当前简化 Inbox 反推行情事实。
