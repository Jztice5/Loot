# 2026-07-28 REQ-0015 常驻监控 Worker 设计

## 背景

- REQ-0014 已提供持久化 Subscription，但 `next_run_at`、Run 账本和恢复语义尚未实现。
- 直接给 Run-Once 外面套无限循环无法区分重复调度、无 Candidate、依赖失败和进程中断。

## 判断过程

- 放弃“一个大事务包住完整决策链”：Provider 网络调用和四段既有事务不能长期持锁。
- 放弃“租约等于幂等”：租约过期可能产生短暂并发，最终仍依赖下游稳定身份和唯一约束。
- 放弃“补跑时读取最新 K 线”：恢复必须读取精确 target_bar_closed_at，否则 Run 身份和输入不一致。
- 将 Run 执行状态和业务 outcome 分离，使 NO_CANDIDATE 成为成功终态而不是失败重试。
- 增加 phase 恢复游标，并明确 checkpoint gap 通过同身份阶段重投收敛，不能把 phase 当事实源。
- 将影响下游 payload 的 evaluated_at 和 request identity 一次绑定，避免重试读取新时钟造成
  相同稳定身份对应不同事实。
- 将 Subscription 调度游标、Run 当前投影和 Attempt 追加证据分离，避免一张表承担三种生命周期。

## 改动点

- 新增 [Crypto 常驻监控 Worker 设计](../../../architecture/runtime/crypto-monitoring-worker-v0.1.md)。
- 新增 [REQ-0015 实施计划](../../../planning/2026-Q3/REQ-0015-crypto-monitoring-worker-plan.md)。
- 固定 Run identity、H1 时间边界、Snapshot 绑定、状态机、租约、退避和配置变化语义。
- REQ-0015 从 Planned 切换为 In Progress；本轮只完成设计和评审，未写生产代码。

## 验证

- 人工对照 Run-Once 四段事务、WatchItem 生命周期、Snapshot identity 和 Signal 幂等约束。
- 设计评审结论为 Accepted for implementation，见
  [评审记录](../../../reviews/2026-Q3/req-0015-monitoring-worker-design-review-2026-07-28.md)。
- 上下文结构检查与链接检查以本轮最终 `scripts/check_context.py` 输出为准。

## 发现的问题

- 当前 Crypto Provider 只有“最近窗口”接口，不能严格补跑历史目标 K 线；实现阶段必须先补
  targeted window 能力。
- 完整 Snapshot 未持久化。V0.1 通过首次 content hash 绑定阻止输入漂移，但数据修正后的自动
  Replay 仍需后续独立需求。

## 当时遗留事项（历史快照）

- REQ-0015 生产代码、0003 migration 和真实双 Worker 验收尚未开始，当前状态以需求管理为准。
