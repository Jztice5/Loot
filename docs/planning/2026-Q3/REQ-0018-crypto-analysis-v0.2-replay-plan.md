# REQ-0018 Crypto 分析模型 V0.2 与 BTC 一年 Replay 实施计划

## 目标

在不改变现有生产规则和 Signal 权限边界的前提下，建立可追溯的 BTC 历史数据、Replay、结果
标签和对照评测能力，再用实证决定 V0.2 是否具备进入运行时的资格。

需求来源：[需求管理 2026-Q3](需求管理-2026-Q3.md)。

当前实施切片：[Crypto Historical Dataset Foundation Implementation Plan](REQ-0018-crypto-historical-dataset-foundation-plan.md)。
对应稳定设计：[Crypto 历史数据集与 Replay 数据基座 V0.1](../../architecture/testing/crypto-historical-dataset-replay-v0.1.md)。

## 开始前设计门禁

实现前必须完成并评审组件设计，至少固定：

- 历史数据来源、时间范围、分页与限流、修正策略、数据集版本和完整性口径。
- Replay 时钟、输入快照重建、规则版本隔离、幂等身份与未来数据隔离。
- Candidate outcome 的观察窗口、MFE、MAE、1R/2R、假突破和先止损/先目标标签定义。
- 入场、失效位、目标位和费用/滑点假设；无法构造有效风险单位时如何标注。
- 探索集、验证集和最终验收集的时间切分，主指标、保护指标、上线阈值与拒绝条件。
- V0.2 输出契约与现有 Candidate、Evidence、Proposal、Policy、Signal 的兼容和版本迁移方案。

未通过该设计评审前，不开始调参或修改生产 PreFilter。

## 实施阶段

1. **数据集与质量基线**
   - 拉取并版本化至少一年 BTC H1 数据，必要时从 H1 确定性聚合 4H。
   - 检查缺失、重复、乱序、闭合时间、异常 OHLCV、Provider 修正和 UTC 边界。
   - 生成 dataset manifest、内容摘要和质量报告，使同一版本可以在新设备复现。
2. **Replay 与结果标签**
   - 复用生产 MarketBar、MarketSnapshot、PreFilter 和规则版本，按历史时钟逐根推进。
   - 固定 Candidate、Snapshot、ReplayRun 和 Outcome identity，重复执行不得产生不同结果。
   - 在 Candidate 之后的独立窗口计算 MFE、MAE、1R/2R、假突破和时效标签。
3. **V0.1 基线报告**
   - 统计覆盖率、LONG/SHORT 分布、分市场状态结果、假突破率和风险收益分布。
   - 检查样本门槛；不足时扩大历史范围或停止结论，不进入 V0.2 调参。
4. **V0.2 单变量研究**
   - 依次比较 4H 市场状态、ATR/突破幅度、成交量确认和回踩确认。
   - 每次只改变一个主要变量，并保留 V0.1 与前一版本的同样本结果。
5. **结构化分析输出**
   - 固定方向、市场状态、证据、观察入场区、失效位、目标位、风险收益和不可操作原因。
   - 保持 Direction 与 PositionSide 分离；分析输出不是下单命令。
6. **未见样本验收与 rollout 决策**
   - 在未参与调参的时间区间重放最终候选版本，检查主指标和保护指标。
   - 通过时以新 rule/workflow version 灰度；未通过时保留研究报告并拒绝切换默认规则。
7. **上下文收尾**
   - 更新架构、需求状态、memory、过程日志、评审和 Replay runbook。
   - 完成全量测试、数据库集成、context check 和代码规范审查。

## 关键约束

- Golden Case 固定产品语义，历史 Replay 测量统计表现；两者不能互相反推或覆盖。
- 特征只能读取 Candidate 发生时及之前的数据；标签只能在 Candidate 产生后计算并与特征隔离。
- 研究结果必须包含失败与无候选样本，禁止幸存者偏差和手工挑图。
- V0.1、V0.2 使用相同数据版本、费用/滑点、观察窗口和标签器比较。
- 原始数据、派生数据、规则、标签器和报告都必须版本化并带内容摘要。
- 研究路径不直接写生产 Signal；运行时切换仍经过 Proposal、Policy Gate 和 Signal State Machine。

## 用户配合点

- 确认 V0.2 的主要交易语义：偏趋势突破、突破回踩，还是两者并行研究。
- 确认统一风险单位和费用/滑点假设，用于 1R/2R 与期望值计算。
- 在基线报告生成后人工复核一组成功、失败和边界案例，再冻结上线阈值。

## 非目标

- 不引入 Agent/LLM、自动下单、账户同步或多市场实现。
- 不在同一需求中实现 Alert Center。
- 不承诺通过回测的规则一定具有未来收益，也不以单一命中率作为上线依据。
