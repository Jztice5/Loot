# 2026-07-14 第二轮地基约束收敛

## 背景

第一轮设计回归拆分了 DecisionProposal、PolicyEvaluation 和 DecisionTicket。继续从
实现可行性复核后，发现若干文档虽已统一术语，但不变量仍不足以阻止错误实现。

## 目标

- 用现有代码复现关键风险，避免只做抽象推理。
- 把确认后的规则提升到 architecture 和 AGENTS。
- 将代码修正收敛成单一先行需求，不与 Golden Case、PreFilter 混做。

## 复现证据

现有 30 个单元测试全部通过，但额外只读验证确认：

```text
不同窗口：same_id=True, same_key=True, bar_counts=2 3
状态迁移：invalid_projection=True
提前闭合：accepted_closed_before_close=True
冲突Ticket：altered_payload_accepted_as_duplicate=True
```

说明当前测试基线没有覆盖 Snapshot 内容身份、闭合时间、投影重校验和完整幂等冲突。

## 判断过程

### Snapshot identity 必须描述完整输入

最新 K 线只能标识窗口尾部，不能标识窗口长度和历史内容。Replay 的输入身份应由完整
有序 MarketBar 事实生成 content hash。

### Policy 幂等与重评必须分开

同一次 evaluation_request 重复投递需要幂等；DEFERRED 到期后的新评估则是新的业务
事实。两者不能共用 `proposal_id + policy_version` 一个唯一键。

### Ticket 必须同时证明授权和新鲜度

PolicyEvaluation ID 只能说明“曾经审核过”，不能说明当前 Signal、TradingPlan 或
Position 仍与审核时一致。Ticket 必须绑定 expected version 和 context_digest，状态机
还要从事实源重新验证授权链。

### Signal 终态不是监控终点

终态实例保持不可变历史，新的市场 setup 使用下一代 SignalInstance。初始化不表达
市场判断，因此 latest_decision_ticket_id 初始为空。

## 文档改动

- 更新系统架构、核心契约、Crypto Provider、决策运行时、监控闭环和状态机设计。
- 将新硬约束提升到根 AGENTS.md。
- 新增 REQ-0009，作为 Golden Case 前的先行修复。
- 更新 README、memory、开发计划、需求管理和文档索引。
- 新增第二轮复核记录，保留复现证据和复核门槛。

## 验证

- `$env:PYTHONPATH='D:\my-projects\Loot\src'; py -3.12 -m unittest discover -s tests -p 'test_*.py'`：30 tests OK。
- `py -3.12 -m compileall src tests`：通过。
- `rg -n ".{101,}" src tests`：无超长代码行。
- 文档修改完成后执行本地 Markdown 链接扫描和 `git diff --check`。

## 当时遗留事项（历史快照）

1. 实现 REQ-0009 并增加六类回归测试。
2. 完成 REQ-0006 Golden Case。
3. 实现 REQ-0005 Crypto PreFilter。
4. 再进入 REQ-0007 和 REQ-0008 的授权与持久化链路。
