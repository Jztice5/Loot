# 2026-07-14 三类时间上下文模型

## 背景

上下文框架完成单一事实源、自动检查和 macOS 适配后，需要进一步回答一条信息属于过去、
当前还是未来。没有时间语义时，历史验证、当前状态和未来计划仍可能在同一文档中混用。

## 目标

- 定义过去式上下文、现在进行时上下文和未来规划上下文。
- 复用现有 architecture、memory、log、review 和 planning，不创建三套重复目录。
- 固定任务从计划到执行再到归档的迁移规则。
- 明确 architecture、AGENTS 和 runbooks 是跨时间稳定上下文。

## 判断

时间语义和文档职责是正交关系：log 的职责是保存过程证据，因此天然承载过去式；memory
的职责是当前仪表盘，因此承载现在进行时；planning 的职责是表达尚未发生的需求，因此
承载未来规划。需求开始后仍在 planning 原条目维护 In Progress 状态，memory 只链接项目
当前焦点，不复制需求正文。稳定架构并不是第四种任务状态，而是从不同时间上下文提炼出的
长期约束。

## 改动

- 新增 `docs/architecture/context/temporal-context-model-v0.1.md` 作为项目权威定义。
- docs 入口增加三类上下文导航。
- AGENTS 增加时间上下文硬约束和迁移动作。
- `vibe-context-manager` 增加可跨项目复用的时间语义模型。
- context check 增加权威文档和三类标记检查。
- memory、planning、季度日志与评审索引同步记录本次变更。

## 验证

```bash
make check
.venv/bin/python main.py
```

实际环境：macOS Apple Silicon，Python 3.13.9，Git 提交 `9d3b85f`。

实际结果：

- context check 通过：45 个 Markdown 文件、117 个本地链接、memory 105 行、Skill 341 行。
- `src`、`tests` 和 `scripts` 的 `compileall` 通过。
- `Ran 41 tests`，`OK`。
- `main.py` 输出 `Hi, PyCharm`。
- 项目 Skill 与全局镜像均通过 validator，SHA-256 为
  `a0f9796ac0846a2ca8bcc0b0fe97e3172d7199d75d21ca9daa77804173989c44`。

## 当时遗留事项（历史快照）

- REQ-0006 开始时，应从 Planned 转为 In Progress，并进入 memory 当前焦点。
- REQ-0006 完成后，应转为 Done，把证据沉淀到 log/review，再从 memory 移除临时状态。
- 2026-Q4 carryover 时验证未来规划跨季度迁移和过去式归档规则。
