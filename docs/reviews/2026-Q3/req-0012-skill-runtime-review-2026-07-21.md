# REQ-0012 Skill Runtime 评审

## 范围

- Skill manifest、精确版本注册、市场与 capability 权限边界。
- 输入输出契约、超时、失败语义和审计可追踪性。
- 与 Agent、Policy、Signal 和持久化边界的一致性。

## 结论

REQ-0012 通过最小基线验收。运行时已经能阻止未注册、跨市场、越权和类型不匹配的 Skill
进入 handler，并能区分成功、失败、超时和拒绝。它没有获得 Signal、Policy 或数据库写权限。

## 已对齐项

- `(skill_id, version)` 精确解析且禁止重复覆盖。
- manifest 类型名与注册的 Python 输入输出类型必须一致。
- run_id、correlation_id、input_snapshot_id、市场、Skill 版本和 UTC 时间进入运行审计。
- handler 异常只记录稳定错误码，不记录可能含敏感信息的异常文本。

## 保留风险

- 内存审计不能跨进程恢复，不能替代 PostgreSQL SkillRun 事实表。
- Python 线程 timeout 不能终止正在运行的函数；V0.1 只允许无副作用的受信 Skill。
- 还没有 Context Builder、Agent allowlist 编排、生产 Skill 或 EvidenceSet 适配器。

## 复核清单

- 接入 Agent 前定义可见上下文、显式 Skill 选择权限和调用预算。
- 接入不可信或外部 Skill 前使用进程隔离，并定义网络、数据库和重试 capability。
- SkillRun 需要持久化时新增 migration、幂等和恢复需求，不直接扩展内存适配器语义。
