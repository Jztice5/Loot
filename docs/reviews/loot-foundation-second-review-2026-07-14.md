# Loot 地基第二轮复核

## 1. 复核范围

- MarketBar、MarketSnapshot 和 Crypto Provider。
- SignalInstance、Signal State Machine 和内存幂等。
- DecisionProposal、PolicyEvaluation、DecisionTicket 授权链路。
- Signal 初始化、终态和下一代生命周期。
- 需求顺序、memory 和 AGENTS 硬约束。

## 2. 总体结论

第一轮已经正确拆分 Proposal、PolicyEvaluation 和 Ticket，但第二轮从“能否安全实现”
继续向下检查后，发现 Snapshot identity、Policy 重评、Ticket 新鲜度、Signal 初始化和
投影校验仍有缺口。

本轮已经把稳定规则补进 architecture 和 AGENTS。当前可以认为“设计约束已定稿”，
但不能认为“现有代码已满足约束”。进入 Golden Case 前先完成 `REQ-0009`。

## 3. 已复现问题

### P1：不同 K 线窗口复用 Snapshot identity

使用同一 FakeCryptoProvider 和 Instrument 分别请求 limit=2、limit=3：

```text
same_id=True
same_key=True
bar_counts=2 3
```

原因是旧 snapshot_key 只绑定最新 K 线，没有绑定完整窗口。

### P1：状态机返回违反时间不变量的投影

原 Signal expires_at 为 08:30，在 09:00 应用迁移后：

```text
invalid_projection=True
expires_at=2026-07-10T08:30:00+00:00
last_transition_at=2026-07-10T09:00:00+00:00
```

原因是 `model_copy(update=...)` 没有重新运行 Pydantic validator。

### P1：未来 K 线可以提前标记为已收盘

当前契约接受 received_at=08:01、closed_at=09:00、is_closed=True 的 MarketBar：

```text
accepted_closed_before_close=True
```

这会绕过 latest_closed_bar 的安全语义。

### P2：相同 Ticket ID 的不同 payload 被当作正常重复

修改已消费 Ticket 的 position_impact 和 summary 后再次提交：

```text
altered_payload_accepted_as_duplicate=True
stored_position_impact=FIRST
```

当前重复检查只比较 Signal ID 和目标状态，没有比较完整授权内容。

## 4. 已提升为稳定约束

- Snapshot identity 使用完整有序 K 线事实的 canonical content hash。
- `is_closed=True` 必须满足 received_at 不早于 closed_at。
- Signal 更新必须重新运行完整契约校验。
- 初始 latest_decision_ticket_id 为 null；终态后创建新 generation。
- PolicyEvaluation 按 evaluation_request_id 幂等，并允许 DEFERRED 在新上下文重评。
- 一个 Proposal 整个生命周期最多一张 Ticket。
- Ticket 绑定 expected_signal_version、业务上下文版本和 context_digest。
- 状态机从 PostgreSQL 验证持久化授权链，不信任调用方构造的 Ticket。
- 相同 Ticket ID 但 payload 指纹不同必须拒绝并审计。

详细设计见：

- [决策运行时与授权链路](../architecture/runtime/decision-flow-v0.1.md)
- [Crypto 行情 Provider](../architecture/market-domains/crypto-market-data-provider-v0.1.md)
- [Signal State Machine](../architecture/signal-state-machine/loot-signal-state-machine-v0.1.md)

## 5. 当前实现阻塞项

- `MarketSnapshot` 尚无 snapshot_content_hash。
- `_build_snapshot` 仍只使用 latest provider_event_id。
- MarketBar 尚未校验闭合时间真实性。
- SignalInstance.latest_decision_ticket_id 仍不可为空，且尚无 generation/setup_key。
- 状态机仍使用不校验更新的 model_copy。
- 重复 Ticket 尚无 payload fingerprint。
- DecisionProposal、可重评 PolicyEvaluation 和新 DecisionTicket 尚未实现。

这些问题统一进入 `REQ-0009`、`REQ-0007` 和 `REQ-0008`，不散落成临时补丁。

## 6. 复核门槛

进入 Golden Case 前：

- `REQ-0009` 的六类回归测试全部通过。
- 不同输入窗口具有不同 Snapshot identity。
- 提前闭合 K 线无法进入快照。
- 状态机无法返回违反 SignalInstance 不变量的投影。
- 初始 Signal 不再伪造 DecisionTicket。
- 修改重复 Ticket payload 会触发冲突。

进入授权链路实现前：

- DEFERRED 重评身份和 Ticket 唯一性已进入契约。
- Ticket 上下文版本和授权事实校验端口已定义。
- 终态后新 generation 的初始化测试已具备。

## 7. 一句话结论

先修复已经证实的地基不变量，再用 Golden Case 定义市场规则；当前不应直接推进
PreFilter、Agent 或 Alert。
