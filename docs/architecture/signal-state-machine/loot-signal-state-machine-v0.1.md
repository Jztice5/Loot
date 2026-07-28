# Loot Signal State Machine 设计文档 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Implemented |
| 版本 | 0.1 |
| 日期 | 2026-07-10 |
| 最后实现校准 | 2026-07-16 |
| 依赖 | 核心契约设计、自选与持仓信号监控闭环 |
| 代码位置 | `src/loot/signals/state_machine.py` |
| 适用范围 | Phase 0：Signal Foundation |

## 1. 设计目标

Signal State Machine 是 Signal 状态事实的唯一写入入口。它消费已经通过
Policy Gate 的 `DecisionTicket`，输出新的 `SignalInstance` 投影和
`SignalEvent`。

目标：

- 由状态机幂等初始化 OBSERVING Signal，并管理 generation。
- 固定 V0.1 合法迁移表。
- 阻止 Agent、Skill 或普通消费者直接改变 Signal 状态。
- 从事实源验证 Proposal、PolicyEvaluation 和 DecisionTicket 授权链。
- 同一个 `DecisionTicket` 重复消费时返回首次结果，不重复生成事件。
- `authorized_transition` 等于当前状态时不生成 `SignalEvent`。
- 在没有数据库前，用内存账本验证状态机语义。

非目标：

- 不实现数据库持久化、乐观锁和 outbox。
- 状态机内部不实现 Policy Gate、市场专属 TransitionPolicy 或 Alert Center。
- 不实现跨进程幂等；V0.1 的账本只用于单进程测试和 Golden Case 准备。
- 不定义市场条件，只执行已准入的状态迁移。

## 2. 调用链

```text
DecisionProposal
-> Policy Gate
-> DecisionTicket
-> SignalStateMachine.apply
-> SignalInstance / SignalEvent
-> Alert Center / Replay / Projection
```

状态机只看到 Policy Gate 签发后的 DecisionTicket，不接收 DecisionProposal，也不负责
在内部重新运行 Policy；但必须通过 `AuthorizationRepository` 核验 APPROVED 结果、摘要、
版本和有效期，不能信任调用方可以任意构造的对象。Phase 0 使用内存适配器，生产实现
必须切换为 PostgreSQL 事实源。

初始化链路：

```text
MonitoringSubscription / New Setup
-> SignalStateMachine.initialize
-> OBSERVING SignalInstance(generation, latest_decision_ticket_id=null)
```

## 3. 合法迁移表

V0.1 严格采用闭环设计文档中的最小迁移表：

| From | To | 说明 |
|---|---|---|
| `OBSERVING` | `ARMED` | 候选进入重点观察 |
| `ARMED` | `TRIGGERED` | 条件触发 |
| `TRIGGERED` | `CONFIRMED` | 触发后确认 |
| `TRIGGERED` | `INVALIDATED` | 触发失败或失效 |
| `CONFIRMED` | `WEAKENING` | 已确认信号开始走弱 |
| `WEAKENING` | `CONFIRMED` | 走弱后重新确认 |
| `WEAKENING` | `RESOLVED` | 信号生命周期完成 |
| `OBSERVING` | `EXPIRED` | 观察态过期 |
| `ARMED` | `EXPIRED` | 预备态过期 |

`INVALIDATED`、`RESOLVED`、`EXPIRED` 当前视为终态，不提供出边。

### 3.1 确定性到期收敛

除初始 `OBSERVING` 外，状态迁移默认必须消费有效的 `DecisionTicket`。唯一受限例外是
状态机根据当前 `SignalInstance` 已持久化且不可变的 `expires_at`，把仍处于非终态的
`OBSERVING` 或 `ARMED` 收敛为 `EXPIRED`。该路径不表达新的市场判断，不读取或改写
Candidate、Proposal、PolicyEvaluation、Position、Direction 或 Actionability。

- 仅在 `expires_at <= detected_at` 时执行，且 `last_transition_at` 固定写为 `expires_at`。
- 产生独立 `SignalExpiryEvent` 和 `loot.crypto.SignalExpired` Outbox 事件；不得伪造、复用或
  消费 `DecisionTicket`。
- `signal_transitions.decision_ticket_id` 仅对这类事实允许为空；常规授权迁移仍必须关联 Ticket。
- 事件 identity 由 `signal_id + expires_at` 的 UUIDv5 确定，重复检测不得增加版本或新事件。
- PostgreSQL workflow 必须在监控身份 advisory lock 内先收敛最新过期 generation，再分配下一
  generation；Worker、Agent、Skill 和 Policy 均不得直接更新 Signal。

## 4. Apply 语义

当前 `SignalStateMachine.apply(current_signal, decision_ticket, authorization_context)`
执行步骤：

1. 以 `decision_ticket.id` 查询内存幂等账本。
2. 命中时核对完整 canonical payload 指纹；一致则返回首次结果，不一致则拒绝。
3. 确认调用方提供的是状态机当前 Signal 投影。
4. 从 `AuthorizationRepository` 加载 Proposal、PolicyEvaluation 和 Ticket，并校验
   APPROVED、引用关系、proposal_digest、policy_version 和授权 payload。
5. 校验 Ticket/Evaluation 有效期、Signal identity、direction、
   `expected_signal_version` 和业务 `authorization_context`。
6. 将 occurred_at 归一化为 UTC，并拒绝倒退或晚于当前 Signal expires_at 的迁移。
7. 如果目标状态等于当前状态，返回 no-op 结果，不生成 `SignalEvent`。
8. 校验合法迁移表。
9. 使用完整 Pydantic 模型校验生成新的 `SignalInstance` 投影：
   - `state = decision_ticket.authorized_transition`
   - `actionability = decision_ticket.actionability`
   - `latest_decision_ticket_id = decision_ticket.id`
   - `last_transition_at = occurred_at`
   - `version = current_signal.version + 1`
10. 生成包含 Candidate、Proposal、Evaluation、Ticket 和 Snapshot 引用的
    `SignalEvent`。
11. 更新内存 Signal 事实，并将 Ticket payload 指纹和首次结果写入幂等账本。

第二轮复核增加以下强制修正规则：

- Ticket 必须绑定 expected_signal_version、业务上下文版本和 context_digest。
- 状态机必须先加载并核对持久化授权链，再登记 Ticket 消费。
- Signal 更新必须重新运行 Pydantic 完整校验；禁止使用跳过 validator 的
  `model_copy(update=...)` 直接形成事实投影。
- occurred_at 必须先归一化为 UTC。
- 迁移时间晚于当前 expires_at 时必须拒绝旧 Ticket 或按明确规则结束当前 generation，
  不能返回 expires_at 早于 last_transition_at 的投影。
- 相同 Ticket ID 只有完整 payload 指纹一致时才视为重复；内容不同必须抛出冲突。

## 5. 幂等和重复消费

V0.1 幂等键：

```text
decision_ticket.id
```

重复消费行为：

- 返回首次迁移结果。
- 不增加 Signal version。
- 不生成新 event_id。
- 如果相同 DecisionTicket ID 的 signal、目标状态、授权摘要、上下文版本、
  actionability、position_impact 或其他 payload 字段不同，抛出
  `DuplicateDecisionConflictError`。

未来接入数据库后，该内存账本应替换为：

- `decision_ticket.consumed_at`
- `decision_ticket.payload_fingerprint`
- `signal_transition` 唯一约束
- outbox 事件唯一约束

## 6. 错误类型

| 错误 | 触发条件 |
|---|---|
| `SignalTransitionMismatchError` | DecisionTicket 与 Signal 的市场、标的或周期不一致 |
| `InvalidSignalTransitionError` | 请求迁移不在 V0.1 合法迁移表 |
| `DuplicateDecisionConflictError` | 同一 DecisionTicket ID 被用于不一致迁移 |
| `UntrustedDecisionTicketError` | Ticket 不存在于事实仓库或 payload 与事实不一致 |
| `InvalidAuthorizationChainError` | Proposal、Evaluation 与 Ticket 授权关系不一致 |
| `ExpiredDecisionTicketError` | Ticket 尚未生效或 Ticket/Evaluation 已过期 |
| `SignalVersionConflictError` | expected_signal_version 与当前 Signal 不一致 |
| `SignalContextConflictError` | WatchItem、TradingPlan、Position 版本或 context_digest 冲突 |
| `ExpiredSignalTransitionError` | occurred_at 晚于当前 Signal expires_at |
| `SignalTransitionTimeError` | occurred_at 早于当前 Signal last_transition_at |

## 7. 测试覆盖

当前单元测试位于 `tests/unit/signals/test_state_machine.py`，覆盖：

- 合法迁移生成事件并更新投影。
- 非法迁移被拒绝。
- 重复 `DecisionTicket` 不重复生成事件。
- 相同 Ticket ID 但 payload 不同被拒绝。
- 同状态 `DecisionTicket` 不生成事件。
- DecisionTicket 与 Signal 身份不一致时拒绝。
- 迁移时间归一化为 UTC，倒退时间和过期迁移被拒绝。
- 迁移后通过完整模型校验重建 SignalInstance。
- 初始 Signal 不需要伪造 latest_decision_ticket_id。
- 非 OBSERVING Signal 缺少 latest_decision_ticket_id 时被契约拒绝。
- 相同 setup 幂等初始化、活跃代冲突和终态后 generation + 1。
- 未登记 Ticket、过期 Ticket、方向不一致、Signal 版本和业务上下文冲突被拒绝。
- SignalEvent 可直接追踪 Candidate、Proposal、Evaluation、Ticket 和 Snapshot。

## 8. 后续扩展

- 接入持久化仓库和乐观锁。
- 引入市场专属 `TransitionPolicy`，但共享状态机仍只负责执行迁移。
- 为 DecisionTicket 消费增加 outbox 事务设计。
- 补 Golden Case，覆盖重复事件、非法迁移和 Alert 去重。
