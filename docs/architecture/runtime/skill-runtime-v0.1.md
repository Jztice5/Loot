# Loot Skill Runtime 设计 V0.1

| 属性 | 值 |
|---|---|
| 状态 | Accepted for REQ-0012 |
| 版本 | 0.1 |
| 适用范围 | Crypto First Vertical Slice 的确定性 Skill 执行边界 |
| 不包含 | Agent、LLM、网络访问、Redis、Alert 和 Signal 写入 |

## 1. 责任边界

Skill Runtime 只负责执行已经由调用方明确选择的、已注册的 Skill，并记录一次可追踪的运行
事实。它不负责发现候选、选择市场、决定是否授权或改变业务状态。

```text
Candidate / Context Builder
    -> explicit skill_id + version
    -> Registry resolve and allowlist check
    -> input type and market check
    -> Skill Executor
    -> SkillRunRecord + typed output
    -> EvidenceSet / DecisionProposal producer
```

硬约束：

1. 市场路由由调用方的确定性上游决定，Skill Runtime 不让 LLM 决定市场。
2. Skill 必须提供唯一 `skill_id`、版本、市场范围、输入类型、输出类型、timeout 和 capability。
3. 未注册、版本不匹配、市场越界或 capability 未授权时，Skill handler 不得执行。
4. Skill 只能返回声明的输出类型；它不能创建 DecisionTicket、修改 Signal 或写入 Position。
5. 超时、异常和拒绝必须产生可区分的 `SkillRunRecord`，不能伪装成成功。
6. 当前实现的审计适配器为内存实现；PostgreSQL 持久化属于后续需求。
7. V0.1 handler 必须是无副作用的纯分析函数。线程超时是调用方响应截止线，Python 无法安全
   强杀已运行线程；超时后的迟到输出会被丢弃，进程隔离属于运行不可信 Skill 时的后续能力。

## 2. 核心契约

### SkillManifest

```text
skill_id
version
markets
input_type
output_type
timeout_seconds
capabilities
```

`markets` 至少包含一个市场；`timeout_seconds` 为正数且受 Runtime 上限约束；capability
只能从平台 allowlist 中选择。

### SkillExecutionRequest

```text
run_id
correlation_id
market
input_snapshot_id
input
```

`run_id` 是一次执行事实的身份，`correlation_id` 贯穿 Candidate 到后续 Evidence 的链路，
`input_snapshot_id` 绑定不可变输入窗口。输入实际类型必须与 manifest 一致；每次重试或 Replay
使用新的 run_id，并保留原 correlation_id 或 replay 追踪关系。

### SkillRunRecord

```text
run_id
skill_id
skill_version
market
status = SUCCEEDED | FAILED | TIMED_OUT | REJECTED
correlation_id
input_snapshot_id
started_at
finished_at
output_digest
error_code
```

拒绝可能发生在 handler 执行前；因此 registry、市场和 capability 校验失败同样要留审计。

## 3. Registry 与执行规则

Registry 的唯一键为 `(skill_id, version)`，重复注册直接拒绝，禁止静默覆盖。解析时必须
精确指定版本，不允许自动选择“最新版本”，避免回放结果漂移。

Executor 的顺序固定为：

1. 解析精确版本。
2. 校验请求市场在 manifest 范围内。
3. 校验 manifest capability 是 Runtime allowlist 的子集。
4. 校验 manifest 类型名与注册定义、输入实例类型一致。
5. 在 manifest timeout 内调用 handler。
6. 校验输出实例类型并记录运行结果。

成功输出只交给调用方；后续 Evidence/Proposal 生产者负责自己的契约校验和持久化事务。

## 4. 故障与安全

| 场景 | Runtime 行为 |
|---|---|
| Skill 未注册或版本不匹配 | `REJECTED`，handler 不执行 |
| 市场越界 | `REJECTED`，handler 不执行 |
| capability 越权 | `REJECTED`，handler 不执行 |
| 输入类型不匹配 | `REJECTED`，handler 不执行 |
| handler 抛出异常 | `FAILED`，保存稳定错误码 |
| 超过 timeout | `TIMED_OUT`，调用方不能把结果当成功 |
| 输出类型不匹配 | `FAILED`，保存输出契约错误 |

Runtime 不接受未声明的网络、数据库或交易能力。Skill 需要外部资源时，必须先增加新的
capability 和对应的受控适配器设计，不能在 handler 内隐式访问。

## 5. 测试与演进

REQ-0012 只验证内存 Runtime 的契约和边界。后续若需要把 SkillRun 作为 PostgreSQL 事实持久化，
必须新增需求，明确表结构、幂等键、迁移角色、失败恢复和历史回放兼容策略。
