# REQ-0005 Crypto Structure PreFilter V0.1

## 背景

REQ-0006 已用 8 个 Golden Cases 固定结构突破产品判断。本需求将同一批预期落成生产
PreFilter，不接 Agent、LLM、Policy 或 Alert。

## 实现

- CandidateEvent 增加必填 direction。
- 新增 CryptoPreFilterInput、CryptoPreFilterResult 和稳定原因码。
- 新增 CryptoStructurePreFilter，使用最新已收盘 K 线与前 3 根已收盘 K 线。
- LONG、SHORT 使用镜像的严格收盘越界规则。
- 无候选结果保留 reason、reference_high、reference_low 和 trigger_bar_id。
- Candidate 发生时间绑定触发 K 线 closed_at，有效期从 snapshot.as_of 延续一个 K 线周期。

## 幂等修正

初版实现曾只把 WatchItem、Snapshot、规则版本和 direction 放入 dedupe_key，但 Candidate
payload 还包含可选 position_id。相同 identity 对应不同 position payload 会形成幂等冲突，
因此最终 identity 同时绑定 `position_id or none`。Position 仍不参与市场方向判断。

## 代码规范复核

- 核心类与方法包含业务描述、调用链和业务规则 docstring。
- 输入输出使用 frozen dataclass，跨模块 Candidate 使用不可变 Pydantic 契约。
- Python 文件无超过 100 字符的代码行。
- Candidate 结果校验原因码、结构边界和触发 K 线的一致性。

## 验证

- 契约与 PreFilter 定向测试：19 个通过。
- 完整 unittest：50 个通过，原 45 个测试全部保留。
- `compileall`：通过。
- context check：通过。

## 当时遗留事项（历史快照）

REQ-0007 继续消费 CandidateEvent，完成 DecisionProposal、PolicyEvaluation、Policy 后
DecisionTicket 和 Signal direction 的授权链路。
