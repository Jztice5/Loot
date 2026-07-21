# REQ-0013 Crypto Run-Once 持久化闭环实施计划

## 目标

在不新增数据库表和常驻运行时的前提下，为现有 Crypto 地基提供一个可重复执行的应用入口。
该入口应能把确定性 demo 或 OKX 真实已收盘 K 线交给 PreFilter，并在产生 Candidate 时通过
既有 Repository、Policy Gate 和 PostgreSQL Signal workflow 完成授权迁移。

## 实施步骤

1. 定义 Run-Once 命令、结果和 provider 端口，固定 demo/live 两种模式的语义。
2. 实现确定性 demo Snapshot 与 OKX live Provider 装配。
3. 编排 PreFilter、Signal 初始化、Evidence/Proposal、PolicyEvaluation/Ticket 和状态迁移。
4. 提供只读取 `LOOT_TEST_DATABASE_URL` 或用户级配置的 JSON CLI。
5. 增加无数据库的应用服务单元测试和会自行清理测试事实的 PostgreSQL 集成测试。
6. 手工执行一次 demo 且不清理，以 DBX 只读查询验证实际保留数据。
7. 运行全量测试、compileall、PyCharm 检查、context check 和代码规范审查。

## 非目标

- 不持久化原始 K 线、MarketSnapshot 或 Candidate payload；`inbox_messages` 只保存完整
  Candidate 消息的指纹，关键语义由 Evidence、Proposal 和 Signal 事实承接。
- 不实现守护进程、定时调度、批量标的扫描、告警投递或失败自动重试。
- 不让应用层绕过 Policy Gate 直接构造 Ticket，也不直接更新 Signal 表。
- 不接入账户、私有 API、仓位同步或下单能力。

## 验收映射

| 验收点 | 证据 |
|---|---|
| demo 稳定产生 LONG Candidate | 应用服务单元测试 |
| live 无 Candidate 时不初始化 Signal | provider 注入单元测试 |
| 完整授权链写入 `loot_test` | PostgreSQL 集成测试 |
| 进程退出后数据保留 | 手工 demo + DBX 只读查询 |
| CLI 不泄露连接信息 | CLI 输出测试与人工审查 |
| 不越过 Policy/Signal 边界 | 代码审查与现有授权链集成测试 |
