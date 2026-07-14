---
name: vibe-context-manager
description: "创建和维护对 vibe coding 友好的项目上下文管理机制，包括架构文档、开发记忆、过程日志、计划、评审、runbook 和 AGENTS 入口约束。适用于用户要求整理项目文档、建立长期上下文、沉淀聊天决策、设计从宏观架构到具体实现的文档分层、维护 memory/log/review/runbook、让 Codex 后续接手项目更顺滑的场景。"
---

# Vibe Context Manager

## 概览

为长期 vibe coding 项目建立一套可恢复、可演进的上下文管理层，让后续 Codex 不需要翻长聊天，也能快速知道项目定位、当前执行、设计边界、需求队列和验证历史。

核心原则：稳定架构放在 `architecture`，当前状态放在 `memory`，推理过程放在 `log`，可重复操作放在 `runbooks`，阶段判断放在 `reviews`。

## 工作流

1. 先扫描现有上下文：
   - 阅读 `README.md`、`AGENTS.md` 和已有 `docs/**` 索引。
   - 优先用 `rg --files` 看项目文件。
   - 查看 `git status --short --branch`，不要覆盖用户已有改动。
2. 判断当前文档形态：
   - 如果已有清晰结构，沿用并扩展。
   - 如果文档散落，再引入下面的默认结构。
3. 把长期稳定设计和短期过程记录拆开。
4. 建立入口索引，让未来 agent 知道先看哪里。
5. 用 `development/memory.md` 记录当前真实状态。
6. 对重要重组或阶段判断写 review memo。
7. 检查链接、路径和空白格式；只有用户要求或任务需要时才暂存。

## 默认目录结构

除非仓库已有更强约定，否则使用：

```text
docs/
  README.md          项目文档总入口
  architecture/      稳定架构设计，从系统级到组件级
  development/       当前记忆固定；过程日志按季度归档
  planning/          需求、计划和季度总览按季度归档
  reviews/           设计评审、代码评审、阶段结论按季度归档
  runbooks/          本地运行、测试、部署、排障步骤
```

时间型资料的推荐结构：

```text
docs/
  development/
    memory.md
    log/
      README.md
      TEMPLATE.md
      yyyy-Qn/
        开发过程总览-yyyy-Qn.md
        yyyy-MM-dd-主题.md
  planning/
    README.md
    yyyy-Qn/
      规划总览-yyyy-Qn.md
      需求管理-yyyy-Qn.md
  reviews/
    README.md
    yyyy-Qn/
      评审记录总览-yyyy-Qn.md
      <主题>-review-yyyy-MM-dd.md
```

季度目录使用事件发生日期所在季度，例如 2026 年 7 月进入 `2026-Q3/`。目录根部的
`README.md` 只做跨季度导航；季度内容由文件名显式带季度的总览文档承载。

推荐的架构分层：

```text
docs/architecture/
  README.md
  system/            宏观架构、核心边界、不可变约束
  <component>/       组件设计或功能闭环设计
  contracts/         API、事件、Schema、状态机契约
  runtime/           Runtime、编排、Policy、Agent、Skill 设计
  persistence/       数据库、迁移、幂等、outbox 设计
  testing/           Replay、Golden Case、契约测试、评测口径
```

只创建马上有内容或明确下一篇文档的目录，避免提前铺一堆空目录。

## 文档职责

### `docs/README.md`

作为人和 agent 的第一入口，包含：

- 先看哪里。
- 架构设计入口。
- 当前项目记忆入口。
- planning、reviews、runbooks 入口。
- 目录职责说明。

### `docs/architecture/README.md`

说明架构文档的分层和归属。它要回答：“这个设计问题该归哪篇文档管？”

### `docs/architecture/system/*`

放系统级稳定决策：

- 项目背景、目标和非目标。
- 核心架构原则。
- 系统上下文和边界。
- 模块、服务或领域职责。
- 可靠性、安全、可观测性、发布策略。
- P1/MVP 范围。
- 给未来 coding agent 的硬约束。

不要放日常 debug、临时任务、实现流水账。

### `docs/architecture/<component>/*`

放组件级或功能闭环设计，包含：

- 问题定义。
- 目标和非目标。
- 模块影响矩阵。
- 领域模型。
- API、事件、命令、状态机、持久化事务。
- 幂等和并发规则。
- 故障处理。
- 测试和验收标准。
- Rollout 和 rollback。

### `docs/development/memory.md`

保持短小、当前、可扫描。包含：

- 当前项目状态。
- 当前实现基线和临时差异。
- 当前活跃需求、阻塞和恢复点。
- 已验证命令和结果。

重要设计或实现完成后更新它，但不要让它变成第二份架构文档。

### `docs/development/log/`

一个重要工作片段一篇日志。`README.md` 做跨季度索引，`TEMPLATE.md` 做模板，
`yyyy-Qn/开发过程总览-yyyy-Qn.md` 汇总本季度日志。

模板章节建议：`背景`、`目标`、`结构图`、`判断过程`、`改动点`、`验证`、
`发现的问题`、`当时遗留事项（历史快照）`。日志只保存过去式证据；仍需执行的事项
登记到需求管理，不能让日志与当前计划竞争。

### `docs/planning/`

放需求级或里程碑级计划。它回答“有哪些需求、状态是什么、依赖和计划队列如何”，不负责
解释架构为什么这样设计。季度内使用 `规划总览-yyyy-Qn.md` 和
`需求管理-yyyy-Qn.md`；不维护与需求管理、memory、log 重叠的季度流水式开发计划。
复杂需求确实需要实施计划时，创建与具体 REQ 绑定的专题计划并从需求条目链接。

### `docs/reviews/`

放设计评审、代码评审和阶段结论。记录：

- 评审范围。
- 总体结论。
- 已对齐设计点。
- 仍然存在的缺口。
- 后续复核清单。
- 一句话结论。

评审按日期进入 `yyyy-Qn/`，每季度维护 `评审记录总览-yyyy-Qn.md`；目录根
`README.md` 只负责跨季度导航。

### `docs/runbooks/`

放可重复执行的操作：

- 本地运行。
- 测试命令。
- 排障流程。
- 部署或回滚步骤。
- 手工验证流程。

Runbook 要直接、可执行，不写哲学。

## Root AGENTS 入口

如果项目重度依赖 Codex，创建或更新根目录 `AGENTS.md`，让未来 agent 按这个顺序读上下文：

1. `docs/README.md`
2. `docs/development/memory.md`
3. `docs/architecture/README.md`
4. 与任务直接相关的 system 或 component 设计文档
5. 相关季度的 development log 或 runbook

硬约束要写进 `AGENTS.md`，不要只留在聊天里。`AGENTS.md` 要短到真的会被遵守。

不要要求每个任务无差别读取完整系统架构。跨领域边界、全局可靠性或架构规则变更才加载
系统级全文；普通组件任务依赖 AGENTS 中的硬约束和对应组件设计即可。

## 单一事实源与加载预算

- 根 README 只保留稳定介绍、快速开始和上下文入口，不复制动态需求状态或计划队列。
- 当前执行、阻塞、恢复点和验证基线只在 `development/memory.md` 维护。
- 需求状态、依赖、验收标准和计划队列只在当前季度需求管理维护。
- development log 只保存过去式证据；其中的遗留判断不作为当前计划指令。
- AGENTS 只规定最小必读入口和硬约束，详细设计按任务渐进加载。
- 同一事实出现冲突时，先确定权威来源并删除其他位置的动态副本，不做多点同步承诺。
- 除单文件体量外，还要关注一次任务的强制加载总量；基础必读过重时优先改为索引和按需加载。

## 时间上下文模型

把项目上下文按时间语义分成三类，但不要为它们重复创建三套目录：

| 类型 | 语义 | 默认载体 |
| --- | --- | --- |
| 过去式上下文 | 已经发生的过程、结果、证据和复盘 | development log、reviews、已完成或归档需求 |
| 现在进行时上下文 | 当前执行、阻塞、恢复点和本机验证 | development/memory.md、In Progress 需求、实时 Git/runtime |
| 未来规划上下文 | 尚未发生的需求、依赖、队列和验收标准 | 需求管理、architecture open questions |

architecture、AGENTS 和 runbooks 属于跨时间稳定上下文，从过去和现在提炼，并约束当前与
未来。任务开始时在 planning 原条目把 Planned/Deferred 转为 In Progress，并把项目级当前
执行链接到 memory；任务完成、取消或被替代时转为 Done/Rejected/Superseded，证据进入
log/review，并从 memory 移除已结束的临时状态。转换是语义和状态迁移，不要求移动需求
文档。未来计划不能冒充实现结果，历史验证不能冒充当前机器复验。

## 内容规则

- 用链接代替复制粘贴。
- 记录稳定决策，不写聊天实录。
- 稳定设计和当前状态分开。
- 记录为什么这样判断，不只记录改了什么。
- 保留真实验证命令和结果，并记录日期、Git 基线、OS、runtime 和依赖初始化方式。
- 区分历史通过与当前机器复验；当前环境无法复现时如实记录阻塞原因。
- 移动文件后同步修正路径。
- 日志中的未决判断必须标为历史快照；当前是否执行以及顺序只看需求管理。
- 不要为了显得完整提前创建庞大空目录。
- 不要悄悄删除用户文档；移动、归档或用清晰链接标记替代关系。

## 季度归档规则

- 只对时间型资料按季度归档：development log、planning、reviews。
- architecture、memory 和 runbooks 按稳定职责或主题维护，不按季度拆散。
- 所有季度总览文件名必须包含 `yyyy-Qn`，不能只依赖父目录表达时间。
- 需求管理文件名必须包含季度标记。
- 新季度创建新目录和新总览；未完成需求迁移时标注来源季度。
- 旧季度归档后不覆盖改写业务结论，修正通过新季度记录或明确勘误链接表达。
- 各时间型目录根 `README.md` 保持固定路径，仅维护跨季度入口和当前季度链接。

## 晋升规则

把信息放到它应该长期存在的最高层级：

| 信息类型 | 放到哪里 |
| --- | --- |
| 临时观察、debug 痕迹、放弃过的方案、一次性推理过程 | `docs/development/log/` |
| 当前执行、阻塞、恢复点和最新验证命令 | `docs/development/memory.md` |
| 可重复操作、启动命令、测试步骤、排障流程 | `docs/runbooks/` |
| 稳定边界、契约、不变量、状态机、架构决策 | `docs/architecture/` |
| 阶段结论、未解决风险、复核清单 | `docs/reviews/` |
| 需求状态、依赖、计划队列和验收标准 | `docs/planning/` |

同一条规则如果出现在两篇过程日志里，或者已经开始影响实现决策，就应晋升到 `architecture` 或 `AGENTS`，日志里只保留链接。

## Memory 瘦身规则

让 `development/memory.md` 像仪表盘，不像知识库：

- 只保留当前状态、当前实现差异、验证命令、活跃需求、阻塞和恢复点。
- 不复制历史索引、完整未完成清单或 Planned 队列；分别链接 log 总览和需求管理。
- 详细设计链接到 architecture。
- 详细过程链接到 log。
- 详细操作链接到 runbook。
- 过期状态要删除或下沉到历史日志。
- 历史入口只保留一条指向 log 总览的链接，不在 memory 维护第二份历史索引。

如果 `memory.md` 已经不能快速扫完，就把细节拆出去并留下链接。

## 自动健康检查基线

长期项目应提供仓库内、可重复执行的上下文检查命令，优先只依赖语言标准库。至少检查：

- 必需入口和索引文件存在。
- Markdown 本地链接目标存在。
- 季度目录和总览、需求管理文件命名正确。
- development log 不使用会被误读为当前指令的“下一步”“后续”或“下一环节”标题。
- memory 和 Skill 没有超过约定体量预算。
- 项目 Skill 与已安装镜像是否一致。
- `git diff --check`。

自动检查负责结构与机械一致性，人工 review 负责判断状态、架构和实现语义是否真实。不要用
“以后再做 linter”替代已经频繁执行且容易漂移的手工检查。

## 收尾归档动作

每次完成一段实质工作后，检查是否需要更新上下文：

1. 稳定边界、契约、状态机、非目标是否变化？更新 `architecture/`。
2. 当前执行、阻塞、恢复点或验证命令是否变化？更新 `development/memory.md`。
3. 需求状态、依赖或计划队列是否变化？更新当前季度需求管理。
4. 是否有值得保留的推理、debug 或放弃方案？新增或更新 `development/log/`。
5. 是否形成阶段结论或风险判断？新增或更新 `reviews/`。
6. 是否出现可复用命令序列？新增或更新 `runbooks/`。
7. 是否有未来 agent 必须遵守的新硬约束？更新根 `AGENTS.md`。

## 迁移模式

重构已有 docs 时：

1. 把每个现有文件映射到一个职责：architecture、memory、log、planning、review 或 runbook。
2. 宏观设计移动到 `architecture/system/`。
3. 功能闭环或组件设计移动到 `architecture/<component>/`。
4. 时间型资料移动到日期对应的 `yyyy-Qn/`，并创建带季度名的总览文档。
5. 增加 `docs/README.md`、`docs/architecture/README.md` 和时间型目录跨季度索引。
6. 创建 `development/memory.md`，只总结当前真实状态。
7. 增加 review memo，说明为什么这样重组。
8. 更新根 README 和 AGENTS 链接。
9. 运行链接扫描和 `git diff --check` 或等价格式检查。

## 验证清单

结束前检查：

- 所有引用的文档都存在。
- 新 agent 能从 `docs/README.md` 找到第一入口。
- `development/memory.md` 反映真实 repo 状态。
- 长期架构文档没有混入临时 todo 和 debug 过程。
- 过程日志没有滞留应晋升为架构规则的内容。
- Review 文档记录了未解决风险和后续复核点。
- Runbook 里的命令真实执行过，或明确标记为计划中。
- 新设备能从 runbook 完成依赖初始化并复现当前验证，不依赖未说明的全局包。
- 当前验证记录带有日期、Git 基线、OS、runtime 和实际命令。
- 时间型资料位于正确季度，季度总览和需求管理文件名包含季度标记。
- 仓库提供可重复执行的上下文健康检查，且本轮实际通过。
- 能运行 `git diff --check` 时，必须通过。

## 上下文健康检查

已有这套结构的仓库，快速审计：

- **入口健康**：新 agent 从 `docs/README.md` 两跳内能到 memory、architecture、runbooks 和当前计划。
- **记忆健康**：`development/memory.md` 与 Git 状态、最近验证命令不矛盾。
- **架构健康**：稳定文档讲决策和边界，不写实现日记。
- **过程健康**：development log 保留推理和证据，不只是泛泛总结。
- **Runbook 健康**：命令可复制运行，或明确标记为计划。
- **Review 健康**：风险、缺口、未定事项在 review 或 architecture open questions 中可见。
- **AGENTS 健康**：要求阅读的路径真实存在，硬约束和当前文档一致。

如果两项以上不健康，先修上下文层，再开始大规模实现。
