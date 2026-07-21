# REQ-0012 Crypto Skill Runtime 实施计划

## 目标

为 Crypto 决策链路提供一个不依赖 Agent、LLM、网络和数据库的最小 Skill Runtime，固定 Skill
版本、市场边界、能力声明、输入输出类型、超时和审计语义。

## 实施步骤

1. 创建 `SkillManifest`、`SkillExecutionRequest`、`SkillRunRecord` 和结果契约。
2. 实现版本唯一的 Registry 与 capability allowlist 校验。
3. 实现同步执行器、输入类型校验、异常/超时状态和内存审计适配器。
4. 增加 Crypto 作用域测试和与现有契约的边界测试，不改变 Signal、Policy 和持久化事实源。
5. 运行全量测试、compileall、PyCharm 检查和 context check。

## 非目标

- 不实现 Agent、LLM 路由、自动 Skill 选择或复杂工作流编排。
- 不允许 Skill 修改 Signal、Position、PolicyEvaluation 或 DecisionTicket。
- 不接入真实网络、Redis、Alert 渠道或新的数据库表。
- 不为 US Equity 和 A-Share 创建业务 Skill。

## 验收映射

| 验收点 | 证据 |
|---|---|
| Manifest 和版本唯一注册 | Runtime 单元测试 |
| Crypto 市场与 capability allowlist | Registry 拒绝测试 |
| 输入类型、业务异常和超时 | Executor 单元测试 |
| run_id、correlation_id、snapshot_id 和状态可审计 | In-memory audit 测试 |
| 不越权触碰 Signal 和 Policy | 运行时边界测试与架构评审 |
