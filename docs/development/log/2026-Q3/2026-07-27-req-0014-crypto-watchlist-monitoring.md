# 2026-07-27 REQ-0014 Crypto WatchItem 与监控订阅

## 背景

- REQ-0013 的 Run-Once 仍可使用临时 WatchItem 身份，数据库没有用户监控意图和调度入口事实。
- REQ-0015 常驻 Worker 需要先获得可持久化、可暂停和可恢复的 ACTIVE Subscription。

## 判断过程

- V0.1 只实现 Crypto H1，不提前定义其他市场的路由和生命周期业务规则。
- WatchItem 是用户监控意图，Subscription 必须由它确定性派生，不能独立编辑。
- 命令幂等使用现有 Inbox；首次结果保存在确定性 Outbox 事件中，重投不能返回后来变化的投影。
- ACTIVE 唯一身份、Instrument 稳定身份和生命周期变更分别使用 advisory lock、行锁及
  `expected_version`，数据库唯一约束作为最终保护。
- `next_run_at` 计算、到期查询、租约和运行恢复属于 REQ-0015，本需求只建立可调度事实表和索引。

## 改动

- 新增 Instrument、WatchItem、MonitoringSubscription 三张表及 0002 SQL migration。
- 新增创建、暂停、恢复、归档应用服务、PostgreSQL Repository 和本地管理 CLI。
- Run-Once 改为强制接收 `--watch-item-id`，并在访问 Provider 前加载 ACTIVE Crypto H1 配置。
- 生命周期同步更新 WatchItem 与全部 Subscription；ARCHIVED 为终态。
- 补充命令重投、身份冲突、版本冲突、非法迁移、事务回滚和 CLI 契约测试。

## 验证

- `& .\.venv\Scripts\python.exe -m pytest -q tests\integration\test_crypto_watchlist.py`：5 passed。
- `& .\.venv\Scripts\python.exe -m pytest -q`：114 passed，0 failed，0 skipped。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts migrations`：通过。
- PyCharm 项目构建成功；新生产代码没有 IDE error/warning。
- 0002 已在 `loot_test` 执行；13 表元数据与 `loot_app` 权限检查通过。
- PyCharm 集成终端创建 WatchItem `1fcb2d4b-15ac-4a7c-b1ee-2bdb668579f9`，Subscription
  `80a2b673-e4fa-5a5b-9709-80dc7a1b6881` 为 ACTIVE H1。
- demo Run-Once 返回 `LONG / ARMED / POLICY_APPROVED`；只读复核确认 Inbox、2 条创建 Outbox
  和 Proposal/Evaluation/Ticket/Signal 方向、状态一致。

## 发现的问题

- 13 张业务表 owner 仍为 `postgres`，与 schema owner `loot_migrator` 不一致；当前不影响
  `loot_app` DML，但正式部署前应单独治理对象所有权。
- 原始 MarketBar、MarketSnapshot 和 Candidate payload 仍未留存，当前链路不能独立 Replay。

## 当时遗留事项（历史快照）

- 常驻调度、`next_run_at` 计算、Run 账本、租约、重试与跨事务恢复由 REQ-0015 负责。
- Alert dispatcher 和提醒去重由 REQ-0016 负责。
