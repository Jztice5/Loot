# 2026-07-14 REQ-0009 地基不变量修正

## 背景

第二轮复核已经通过可执行样例复现四类问题：不同 K 线窗口复用 Snapshot identity、
未来 K 线提前声明收盘、状态机跳过模型校验形成非法投影、相同 Ticket ID 的不同内容
被当作正常重复。本次只修这些已证实的不变量，不提前实现 Golden Case、PreFilter、
Policy Gate 或数据库。

## 关键决策

### Snapshot 由完整事实内容寻址

`MarketSnapshot.from_bars` 成为统一构造入口。canonical 内容包含 Provider、市场、标的、
周期、UTC as_of，以及按 opened_at 排序的全部 K 线事实。派生 UUID 不参与 hash；Decimal
消除无意义尾零，datetime 固定转为 UTC ISO-8601，再以紧凑 JSON 计算 SHA-256。

契约 validator 会重新计算 hash、snapshot_key 和稳定 UUID，避免其他生产者传入一组
彼此不一致的身份字段。

### 闭合状态必须符合真实时间

`is_closed=True` 时，`received_at` 不能早于 `closed_at`。Snapshot 的 as_of 不能早于
任何已闭合 K 线的 closed_at。未收盘 K 线仍可进入显式允许盘中数据的 Snapshot。

### 初始 Signal 不伪造授权

`latest_decision_ticket_id` 改为可空；没有 Ticket 时只允许处于 OBSERVING。Signal 同时
携带从 1 开始的 generation 和非空 setup_key。状态机 initialize/next-generation 入口
仍属于 REQ-0007，本次只固定契约和内存运行时语义。

### 状态机完整重建投影

occurred_at 先归一化为 UTC。早于 last_transition_at 的时间被拒绝；晚于 expires_at 的
迁移被拒绝。合法迁移使用 `SignalInstance.model_validate` 完整重建投影，不再通过
`model_copy(update=...)` 绕过跨字段 validator。

### Ticket 幂等需要 ID 和完整内容同时一致

内存账本记录首次 Ticket canonical payload 的 SHA-256 指纹和迁移结果。相同 ID、相同
payload 返回首次结果；相同 ID、任一 payload 字段不同则抛出
`DuplicateDecisionConflictError`。

## 代码与测试

主要修改：

- `src/loot/contracts/market_data.py`
- `src/loot/domains/crypto/market_data.py`
- `src/loot/contracts/signals.py`
- `src/loot/signals/state_machine.py`
- 对应 contracts、Provider 和 state machine 单元测试

新增 11 个回归测试，覆盖不同窗口、历史内容和闭合状态、提前闭合、Snapshot as_of、
初始 Signal、重复 Ticket 冲突、UTC 归一化、过期迁移和倒退时间。

## 验证

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
py -3.12 -m unittest discover -s tests -p 'test_*.py'
py -3.12 -m compileall -q src tests
```

结果：

```text
Ran 41 tests
OK
compileall passed
No Python lines exceed 100 characters.
git diff --check passed with line-ending warnings only.
```

PyCharm MCP 本轮未暴露 Loot 项目连接，因此验证使用同一工作区的 PowerShell 和
Python 3.12 完成。

## 后续

1. `REQ-0006`：先把 Crypto Golden Case 输入和业务预期写成可读样例。
2. `REQ-0005`：按 Golden Case 实现只读取已收盘 K 线的 PreFilter。
3. `REQ-0007`：再实现 Signal 初始化入口和 Proposal/Policy/Ticket 授权链。
4. `REQ-0008`：最后把内存语义升级为 PostgreSQL 事务和跨进程幂等。
