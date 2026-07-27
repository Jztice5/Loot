# REQ-0014 Crypto WatchItem 与 MonitoringSubscription 实施计划

## 目标

为 Crypto Run-Once 建立持久化监控身份，让标的、用户自选、周期、路由和配置版本成为
PostgreSQL 事实，并为后续常驻 Worker 提供 ACTIVE Subscription 查询入口。

## 实施步骤

1. 收紧 Instrument、WatchItem 和 MonitoringSubscription 契约一致性与生命周期状态。
2. 新增 `instruments`、`watch_items`、`monitoring_subscriptions` SQLAlchemy schema 和增量 SQL。
3. 实现创建、暂停、恢复、归档命令，以及 Inbox、Outbox、幂等和乐观版本处理。
4. 提供本地管理 CLI，并让 Run-Once 只接受数据库中 ACTIVE 的 Crypto H1 WatchItem。
5. 覆盖成功、重投、身份冲突、版本冲突、非法迁移和事务回滚测试。
6. 在 `loot_test` 执行增量 SQL 后完成真实 PostgreSQL 集成验收。
7. 完成代码规范审查、全量测试、compileall、context check 和文档收尾。

## 非目标

- 不实现用户体系、通用 Web CRUD、TradingPlan、Position 或 PositionEvent。
- 不实现 scheduler、常驻 Worker、Alert、Replay、Agent 或自动交易。
- 不保存 MarketSnapshot 或 MarketBar；K 线决策回看由后续独立需求实现。
- 不创建 US Equity 或 A-Share 的路由、订阅或领域逻辑。

## 验收映射

| 验收点 | 证据 |
|---|---|
| 创建形成 Instrument、WatchItem、Subscription 和 Outbox | Repository 集成测试 |
| 相同 request 重投不产生重复事实 | Inbox 幂等集成测试 |
| ACTIVE 唯一和恢复冲突 | 唯一约束与生命周期测试 |
| ARCHIVED 不可恢复 | 应用单元测试与 Repository 集成测试 |
| Run-Once 使用真实监控身份 | CLI/配置加载测试与真实 demo |
| 数据库失败整事务回滚 | 集成测试 |
