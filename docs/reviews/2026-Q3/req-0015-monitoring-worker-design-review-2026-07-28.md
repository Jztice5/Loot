# REQ-0015 Crypto 常驻监控 Worker 设计评审

## 评审范围

- H1 调度边界、Run identity、Snapshot 输入绑定。
- Run/Attempt 状态机、租约、并发 claim、失败分类和恢复语义。
- WatchItem 生命周期、Run-Once 四段事务及下游幂等边界。
- PostgreSQL 表职责、Worker CLI、测试和 rollout 计划。

## 结论

设计通过，状态为 **Accepted for implementation**。方案没有引入新的中间件，也没有把市场判断、
Policy 或 Signal 写权限搬进 Worker。Run 账本解决跨事务恢复，Attempt 保留执行证据，租约负责
正常执行所有权，既有稳定业务身份和数据库约束继续承担最终幂等。

本结论只代表设计可进入实现，不代表 REQ-0015 功能已完成或数据库已经迁移。

## 已对齐项

- Run ID 精确绑定 subscription、target_bar_closed_at 和 workflow_version。
- Worker 必须获取目标 H1 窗口，禁止用最新窗口替代历史补跑目标。
- Snapshot identity/content hash 在进入决策链前绑定，重试输入变化按冲突失败。
- 状态与 outcome 分离，NO_CANDIDATE 是 COMPLETED，不消耗重试预算。
- PENDING/RETRY_WAIT 配置失效时取消；RUNNING 使用已绑定版本完成，暂停只影响新 Run。
- 网络调用不持有长事务；claim、状态更新和 Attempt 写入使用短事务。
- lease token 加 version 防止旧 owner 覆盖，SKIP LOCKED 支持多 Worker。
- 恢复重跑使用原 run_id，并复用 Candidate、Policy、Ticket、Signal 和 Outbox 幂等链。
- phase 只作为恢复游标；阶段事务已提交但 checkpoint 落后时，按相同身份重投并恢复首次事实。
- 进入下游 payload 的 evaluated_at 和阶段 request identity 首次绑定后必须跨 Attempt 复用。

## 评审中修正

1. 原始想法只要求“读取最近已收盘 K 线”，无法正确恢复漏掉的历史周期，现已提升为精确
   `target_bar_closed_at` Provider 能力。
2. 原始想法把所有终态放在 Run status，无法区分执行状态和业务结果，现拆分 status/outcome。
3. 原始想法把 lease 视为唯一防重手段，现明确 lease 仅负责所有权，下游幂等是最终保护。
4. 原始想法未定义暂停对运行中任务的影响，现固定为不启动新 Run、已 RUNNING 按绑定配置完成。
5. 初稿只定义 Run 总状态，无法观察跨事务恢复位置，现增加 phase 并明确 checkpoint 不能替代
   各阶段事实源。
6. 现有 Run-Once 默认每次读取当前时钟，直接重跑会让相同评估身份对应不同 payload；现增加
   阶段输入一次绑定规则，并把 Attempt 时间与业务事实时间分离。

## 实现门禁

- 先提交强类型 Run/Attempt 契约和纯状态迁移测试。
- SQL 必须包含组合约束、唯一键、due/lease 索引和 lost-lease 条件更新。
- Provider targeted window 未完成前，不实现伪补跑 Worker。
- 至少两个真实 PostgreSQL Worker 的并发 claim/reclaim 测试通过后，才允许启用 `--loop`。
- 必须覆盖“阶段事实已提交、phase 尚未推进”的中断窗口，不能只测试阶段调用前失败。
- 0003 migration 仍由 `loot_migrator` 在 `loot_test` 先执行，应用继续使用 `loot_app`。

## 保留风险

- 不保存完整 Snapshot，历史修正会使同一 Run 进入 INPUT_CHANGED，需要未来 Replay 治理。
- 单进程 loop 没有操作系统服务守护；进程拉起策略属于部署工作，不属于业务 Worker。
- Outbox dispatcher 尚未实现，Run 事件暂时只能保存在数据库中等待后续消费。
