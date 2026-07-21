# REQ-0008 持久化验收评审

## 范围

- 审查 Crypto 决策链路从 Inbox、授权、Signal 到 Outbox 的 PostgreSQL 事实持久化语义。
- 审查 `loot_test` 上的真实并发、事务回滚、恢复和应用角色权限验证。

## 结论

REQ-0008 通过验收。`loot_test` 上的 7 个真实 PostgreSQL 集成测试和完整 78 个测试均通过；
持久化链路满足本阶段的幂等、并发控制和 Outbox 事实恢复要求。

## 已对齐项

- `loot_app` 只能进行 DML，不能创建 schema 对象。
- Signal 初始化、Policy 评估和 Ticket 消费均有真实数据库并发或冲突覆盖。
- Outbox 未发布记录可恢复；Outbox 冲突会使同一 Signal 事务回滚。
- 本地连接凭据位于用户目录或环境变量，测试认证失败信息经过脱敏。

## 保留风险

- 10 张业务表的 owner 仍为 `postgres`，与 `loot` schema owner `loot_migrator` 不一致；当前权限
  验收通过，但后续运维变更需明确表 owner 治理策略。
- DBX 保存的 `loot_app` 测试连接在本地口令轮换后需要连接维护者手动更新。
- 本需求保存 Outbox 事实和恢复查询，未实现生产 Outbox dispatcher、失败重试调度或最小 Replay。

## 复核清单

- 后续部署需求登记时，单独定义目标环境、迁移执行角色、表 owner 策略和回退方案。
- 启动 Alert 或 dispatcher 前，补齐 Outbox 发布确认、失败退避和可观察性验收。
