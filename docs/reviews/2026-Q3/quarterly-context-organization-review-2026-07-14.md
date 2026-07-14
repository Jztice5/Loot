# Loot 上下文文档季度化评审

> 状态：Superseded（部分规则已被取代）
>
> `superseded_by`：[动态上下文单一事实源评审](context-source-simplification-review-2026-07-14.md)。
> 本文保留为历史记录；其中“每季度必须维护开发计划”的规则不再适用。

## 1. 评审范围

- development log、planning 和 reviews 的目录规模。
- 季度目录和文件命名是否方便人和 Codex 查询。
- architecture、memory、runbook 的稳定入口是否受影响。
- 跨季度滚动和历史需求迁移规则。

## 2. 结论

采用“稳定知识按职责、时间资料按季度”的混合结构。时间型资料进入 `yyyy-Qn/`，季度
总览、需求管理和开发计划的文件名同时带季度标记。各时间型目录根 `README.md` 仅提供
跨季度导航。

## 3. 已确认规则

- development log、planning 和 reviews 按事件日期归档到季度目录。
- architecture、memory 和 runbook 不按季度拆分。
- 总览文件不能只命名为 README，必须显式包含 `yyyy-Qn`。
- 需求管理和开发计划必须显式包含季度标记。
- 未完成需求跨季度迁移时记录来源，旧季度业务结论不覆盖改写。
- docs 总入口和 memory 指向当前季度，历史季度从跨季度索引进入。

## 4. 风险与控制

| 风险 | 控制方式 |
|---|---|
| 文件移动造成链接失效 | 每次季度滚动执行 Markdown 本地链接扫描 |
| 同一需求在两季度重复且状态冲突 | 新季度标注来源，旧季度归档后不更新当前状态 |
| architecture 被误当历史资料归档 | AGENTS 明确禁止 architecture 按季度拆分 |
| 根 README 重新堆积季度内容 | 根入口只维护季度链接，不复制季度明细 |

## 5. 一句话结论

季度标记必须同时体现在目录和总览文件名上；稳定知识入口保持不动。
