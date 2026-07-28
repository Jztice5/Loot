# REQ-0015 Crypto 常驻监控 Worker 代码评审

## 结论

代码规范、静态评审和真实 PostgreSQL 验收 **Accepted（通过）**。REQ-0015 的既定 Worker
边界、并发恢复和端到端成功路径均已验证。

## 已复核

- 应用层只编排 Provider、Run-Once 和 Monitoring Repository，没有创建 Ticket 或直接写 Signal。
- Run、Attempt、Snapshot、phase、lease 和 outcome 使用强类型契约，非法组合同时由 Pydantic 和
  PostgreSQL CHECK 约束拒绝。
- Run identity 使用 subscription、target_bar_closed_at 和 workflow_version 的 UUIDv5；配置版本进入
  execution_context_digest，不替代运行身份。
- Provider 支持精确目标窗口，错位、未闭合和数量不足不会回退到当前最新 K 线。
- Run-Once 消费预加载 Snapshot，阶段回调发生在对应事实事务提交之后；checkpoint 落后时可用原身份重投。
- claim 使用 SKIP LOCKED，状态写入使用 lease_token + version；过期 STARTED Attempt 转为 ABANDONED。
- Provider 网络请求不持有 Monitoring Repository 事务；数据库不可用时保留租约等待过期恢复。
- 输出、异常和 Attempt details 不包含 DSN、SQL 或完整 Provider payload。
- Python 命名、类型、结构化业务 docstring、步骤/决策注释和异常边界符合项目 Python 规范。

## 评审中修正

1. MarketSnapshot 原指纹包含 as_of/received_at，导致同一历史窗口重抓时身份漂移；已把采集时间
   与业务输入身份分离，同时保留价格、成交量、窗口和闭合状态指纹。
2. 增加 run_id/run_key 重新推导校验，防止调用方构造不一致稳定身份。
3. 增加 Snapshot 与 decision_evaluated_at 同时绑定约束，禁止重试重新读取业务评估时钟。
4. 增加 FINISHED 只能与 COMPLETED 同时出现的契约和数据库约束。
5. Policy checkpoint 后按数据库 Ticket expires_at 复核，已过期授权不能用旧 evaluated_at 继续消费。
6. PostgreSQL insert 幂等判断由 `rowcount` 改为 `RETURNING id`，避免实际插入与返回结果分叉。
7. materialize 与 claim 绑定同一 workflow_version，禁止不同版本 Worker 交叉消费。
8. 测试清理按 WatchItem 反查 Run，保证外键顺序和共享测试库恢复能力。

## 验证证据

- 全量：134 passed。
- 过期 Signal 收敛集成测试：8 passed，覆盖无 Ticket 迁移、Outbox 和下一 generation。
- PostgreSQL Worker 集成测试：3 passed。
- Demo Worker：`COMPLETED / FINISHED / SIGNAL_TRANSITIONED`，完整事实链存在。
- OKX public REST：4 根精确目标 H1 K 线全部闭合。
- compileall、PyCharm build 和新增生产文件 problem inspection 通过。
- context check 通过。

## 保留风险

- `--loop` 尚未部署为常驻系统进程，部署时仍需配置守护、日志采集和优雅停止。
- 已过期但尚未进入终态的 Signal 会阻止新 generation；该问题已由 State Machine 的确定性
  `expires_at` 收敛修复。Worker 仍不得通过直接写状态规避；0004 SQL migration 已在 `loot_test`
  执行，PostgreSQL 集成测试和全量回归已通过。
