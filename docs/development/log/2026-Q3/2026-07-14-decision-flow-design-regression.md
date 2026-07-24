# 2026-07-14 决策链路设计回归

## 背景

Crypto K 线 Provider 和 Signal State Machine 已经具备 Phase 0 骨架，下一步原计划直接
实现 Candidate PreFilter 和 Candidate 到 Signal 串联。设计复核发现，宏观文档、契约
文档和状态机对 DecisionTicket 的 Policy 前后语义不一致。

## 目标

- 回归宏观设计和端到端闭环，而不是继续增加组件。
- 消除 Policy Gate 前后对象的类型歧义。
- 固定第一条 Crypto 闭环的实现顺序。
- 把稳定结论同步到 architecture、planning 和 memory。

## 判断过程

### DecisionTicket 不能同时表示建议和授权

如果 Agent、Decision Skill 或 deterministic builder 可以直接创建状态机接受的
DecisionTicket，Policy Gate 只能依赖调用约定，类型系统无法阻止绕过。

因此拆分为：

```text
DecisionProposal：待审核建议
PolicyEvaluation：审核事实
DecisionTicket：已授权凭证
```

### Policy 不应静默修改 Proposal

V0.1 只允许批准、拒绝或延后。需要改变目标状态或证据时生成新 Proposal，以保留
完整审计和 Replay 语义。

### Golden Case 应先于 PreFilter

普通上涨、收盘突破和未收盘突破是产品判断，不应由已经写好的规则反推。先固定输入
和预期，再实现 PreFilter，可以降低算法实现绑架需求定义的风险。

### Position 不是市场结构真假的来源

Position 可以改变用户相关性和提醒优先级，但不能改变同一市场结构是否成立。未来的
持仓风险监控需要独立候选或 SignalType。

### Signal 初始化也需要唯一入口

DecisionProposal 需要引用既有 signal_id。初始 OBSERVING Signal 由状态机初始化入口
根据 MonitoringSubscription 幂等创建；它不表达市场判断，因此无需 Ticket，但后续
任何迁移都必须经过 Policy Gate。

## 改动点

- 新增 `docs/architecture/runtime/decision-flow-v0.1.md`。
- 修正系统宏观架构、核心契约、监控闭环和状态机文档。
- 调整 REQ-0005、REQ-0006、REQ-0007 的推进顺序和验收标准。
- 新增 REQ-0008，承接跨进程幂等、事务和 Outbox。
- 更新 README、文档索引、开发计划和 memory。
- 新增端到端设计回归评审，登记当前代码迁移差距。

## 验证

- 使用 `rg` 复核 DecisionProposal、PolicyEvaluation、DecisionTicket 的上下游语义，
  当前稳定文档未发现 Policy 前 Ticket 残留表达。
- 使用上下文健康检查脚本式命令复核文档链接，结果为 `Markdown links OK`。
- 使用 `git diff --check` 检查 Markdown 格式，检查通过，仅有行尾转换提示。
- 本轮未修改 Python 代码，因此不新增代码测试基线。

## 发现的问题

- 当前 `src/loot/contracts/signals.py` 的 DecisionTicket 仍是 Policy 前对象。
- 当前状态机使用 `suggested_transition`，后续应迁移为 Ticket 的
  `authorized_transition`。
- 当前内存幂等不能覆盖重启、多实例和消息确认前崩溃。

## 当时遗留事项（历史快照）

1. 先完成 REQ-0006 Golden Case。
2. 再实现 REQ-0005 Crypto Candidate PreFilter。
3. REQ-0007 先迁移 DecisionProposal 和 DecisionTicket 契约，再串联状态机。
4. REQ-0008 落地 PostgreSQL 事务、唯一约束和 Outbox。
