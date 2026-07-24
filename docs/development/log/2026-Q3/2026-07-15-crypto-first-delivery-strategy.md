# Crypto First 交付策略

## 背景

Loot 的最终产品覆盖 Crypto、US Equity 和 A-Share，宏观架构也为三个市场保留独立
bounded context。但原路线图只写“建议优先 Crypto”，闭环实施步骤仍包含三个市场 stub，
容易被理解为当前并行开发三个市场。

## 设计判断

- 当前只用 Crypto 搭建第一条完整纵向闭环。
- Crypto 初版范围从 Provider、Snapshot、Golden Case 和 PreFilter，一直覆盖 Candidate、
  授权决策、Signal、Persistence、Alert 和最小 Replay。
- contracts、runtime、persistence 和 alert 只实现 Crypto 闭环真实需要的平台能力。
- Crypto 完成验收和复盘前，不实现 US Equity 或 A-Share 的 Provider、规则、Agent、
  Skills、Policy 和 Signal 业务逻辑。
- 不根据尚未实现市场的假设提前抽象通用业务规则。
- Crypto 稳定后先复盘和提炼已验证能力，再分别启动另外两个 bounded context。

## 文档调整

- 将系统路线图 Phase 2 明确为 `Crypto First Vertical Slice`。
- 删除“第一条端到端实现选择哪个市场”的过期开放问题。
- 将闭环实施步骤从三市场 stub 改为 Crypto 单市场纵向实现。
- 在需求管理增加阶段门禁，并将 US Equity 和 A-Share 明确标为 Deferred。
- 将该顺序提升到 `AGENTS.md`，约束后续 Codex 不并行铺设市场业务。

## 验证

- 运行项目上下文健康检查。
- 检查 architecture、planning、memory 和 AGENTS 对交付顺序的表述一致。
