# Loot 端到端设计回归评审

> 第二轮实现可行性复核见
> [Loot 地基第二轮复核](loot-foundation-second-review-2026-07-14.md)。第二轮发现的
> Snapshot 和状态机不变量优先级高于本文原推进建议。

## 1. 评审范围

- 系统宏观架构。
- 核心 contracts。
- 自选与持仓信号监控闭环。
- Signal State Machine。
- Crypto 行情 Provider 后续规划。
- Candidate、Policy、Signal、Position 和 Alert 的职责边界。

本次只评审并校准设计，不推进 Python 业务实现。

## 2. 总体结论

Loot 的产品定位、三市场边界、Agent 权限和状态机方向成立。主要设计缺口是
`DecisionTicket` 同时承担 Policy 前提案和 Policy 后授权凭证，导致类型无法证明
“已经过 Policy Gate”。

本轮已将权威链路统一为：

```text
MarketSnapshot
-> CandidateEvent
-> EvidenceSet
-> DecisionProposal
-> PolicyEvaluation
-> DecisionTicket
-> Signal State Machine
-> SignalEvent
-> Alert Policy
```

授权链路设计方向成立，但进入 Golden Case 前先完成 REQ-0009 的地基不变量修正；
REQ-0007 前还必须完成现有 DecisionTicket 契约迁移。

## 3. 已解决问题

### P1：Policy 前后共用 DecisionTicket

已解决：

- Policy 前统一为 `DecisionProposal`。
- Policy Gate 必须记录 `PolicyEvaluation`。
- 只有 APPROVED 才签发 `DecisionTicket`。
- Signal State Machine 只接受 Policy 后 Ticket。

### P1：Candidate 到 Signal 规划绕过 Policy Gate

原 REQ-0007 计划由 deterministic builder 直接创建 DecisionTicket。现已改为先生成
DecisionProposal，再经过最小 Policy Gate 签发 Ticket。

### P2：开发顺序由实现反推需求

原计划先实现 PreFilter，再补 Golden Case。现已调整为先固定普通上涨、收盘突破、
未收盘突破和重复输入四类预期，再实现规则。

### P2：Position 与市场信号语义混合

已明确 Position 可以影响 Policy、优先级、position_impact 和提醒语义，但不能改变
市场结构信号的真假。持仓专属风险应使用独立候选或 SignalType。

### P2：事务和因果链不完整

已补充 Candidate、Policy 和 Signal 三个事务边界，以及 snapshot、candidate、proposal、
policy、ticket、transition、alert 的直接引用链。

### P2：初始 Signal 创建入口未定义

已明确 MonitoringSubscription 激活后，由 Signal State Machine 初始化入口幂等创建
OBSERVING Signal。初始化之后的任何状态变化都必须持 DecisionTicket，其他组件不能
为了跑通链路自行创建 Signal。

## 4. 当前实现差距

### P1：Python DecisionTicket 仍是 Policy 前对象

`src/loot/contracts/signals.py` 当前把 DecisionTicket 定义为“进入 Policy Gate 前的
决策票据”，而 `SignalStateMachine.apply` 又把同一类型当作已通过 Policy 的输入。

处理要求：

- REQ-0005 和 REQ-0006 不新增对旧 Ticket 的依赖。
- REQ-0007 先把旧类型迁移为 DecisionProposal。
- 再新增包含 policy_evaluation_id、proposal_digest、authorized_transition 和有效期的
  DecisionTicket。

### P1：幂等仍是单进程语义

状态机内存账本只能支持 Phase 0 测试。跨进程恢复、服务重启和并发消费需要
REQ-0008 的 PostgreSQL 唯一约束、乐观锁和 Outbox 事务。

### P2：Policy Guard 尚未定义为代码契约

设计已明确最小 PolicyEvaluation，但 DataQualityGuard、MarketRuleGuard、
SkillVersionGuard、PositionConsistencyGuard 和 TransitionPolicy 的输出契约尚未实现。
REQ-0007 只实现最小必要 Guard，不提前铺完整 Agent Runtime。

## 5. 后续复核清单

- Golden Case 是否先于 PreFilter 实现提交。
- PreFilter 是否只使用 `latest_closed_bar`。
- 旧 DecisionTicket 是否已完整迁移为 DecisionProposal。
- Policy 拒绝是否保证没有 Ticket 和 SignalEvent。
- Ticket 是否包含 Policy 证明、有效期和稳定幂等键。
- Signal 迁移是否在一个事务中写消费记录、投影、Transition 和 Outbox。
- Position 是否只影响用户相关语义，不改变市场事实。
- Replay 是否能从 snapshot_id 还原到 signal_event_id。

## 6. 一句话结论

设计已经从“组件都存在”收敛为“授权链路可证明”；第二轮复核后，下一步先修复
REQ-0009，再写 Golden Case 和 PreFilter，暂不接 Agent、Alert 或更多行情类型。
