# REQ-0015 Crypto 常驻监控 Worker 与运行恢复实施计划

## 目标

在不改变 Crypto 决策链事实所有权的前提下，让 ACTIVE H1 Subscription 自动形成稳定 Run，
并在重复调度、暂时失败、租约过期和进程重启后安全恢复。

权威设计：[Crypto 常驻监控 Worker 与运行恢复设计 V0.1](../../architecture/runtime/crypto-monitoring-worker-v0.1.md)。

## 实施阶段

1. **契约与纯状态规则**
   - 定义 MonitoringRunStatus、MonitoringRunPhase、MonitoringRunOutcome、AttemptStatus、
     失败分类和状态迁移。
   - 固定 deterministic run_key、execution_context_digest 和 Snapshot 绑定规则。
   - 固定阶段 request identity 和 payload 时间的一次绑定、重试复用规则。
2. **PostgreSQL 事实层**
   - 增加 monitoring_runs、monitoring_run_attempts、约束、索引和增量 SQL。
   - 实现到期物化、claim/reclaim、完成、重试、失败、取消和 lost-lease 防护。
3. **精确行情输入**
   - 为 Crypto Provider 增加截至 target_bar_closed_at 的窗口读取能力。
   - 验证目标 K 线闭合时间、received_at 和 Snapshot content identity。
4. **Worker 编排**
   - 复用 CryptoRunOnceService，支持预加载 Snapshot、稳定 run_id 和阶段 checkpoint。
   - 增加 `--once`、`--loop`、安全测试库检查和脱敏输出。
5. **可靠性测试**
   - 覆盖重复物化、并发 claim、租约过期、旧 token、退避、预算耗尽和进程恢复。
   - 在 `loot_test` 使用两个并发 Worker 完成真实 PostgreSQL 验收。
6. **运行验收与上下文收尾**
   - 执行 migration、全量测试、compileall、PyCharm 检查、context check。
   - 保留一条可查询 Run/Attempt 事实并完成过程记录与代码评审。

## 实施顺序约束

- 先契约、状态机和 SQL，再实现 Repository 和 Worker。
- 不用 sleep 驱动单元测试；时钟和退避时间必须可注入。
- 不在 Provider 网络调用期间持有数据库行锁或事务。
- 任何恢复路径都使用原 run_id 和原 Snapshot identity，不生成替代业务身份。
- 重试不能重新生成进入下游事实指纹的 evaluated_at、request_id 或 correlation identity。
- `--loop` 只能在 `--once` 和真实 PostgreSQL 恢复测试通过后启用。

## 验收映射

| 需求验收点 | 设计/测试证据 |
|---|---|
| 同一 H1 周期最多一个有效 Run | deterministic run_key、唯一约束、并发物化测试 |
| 重复调度和重启不重复下游事实 | 稳定 run_id、阶段幂等、恢复集成测试 |
| Provider 暂时失败退避 | 失败分类、Attempt 审计、可注入时钟测试 |
| PAUSED/ARCHIVED 不启动新 Run | 启动前配置重检与 CANCELED 测试 |
| 中断和 lease 过期可恢复 | SKIP LOCKED、lease token/version、双 Worker 测试 |
| 跨事务阶段可恢复 | phase checkpoint、同身份阶段重投、checkpoint gap 测试 |

## 非目标

- 不实现 Redis/Celery/Kafka、WebSocket、多市场调度、UI、Alert、Replay 或 Agent。
- 不把完整行情留存混入本需求；只绑定 Snapshot identity 和 content hash。
