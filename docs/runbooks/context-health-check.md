# 上下文健康检查

## 使用时机

- 每次完成一段实质设计或实现后。
- 接手项目前感觉上下文不清楚时。
- 文档移动、重命名或新增重要约束后。
- 准备开始大规模实现前。

## 自动检查

macOS / Linux：

```bash
make context-check
```

Windows PowerShell：

```powershell
& .\.venv\Scripts\python.exe scripts\check_context.py
```

`scripts/check_context.py` 只使用 Python 标准库，检查：

- 必需上下文入口是否存在。
- 根 README 是否把当前事实委托给 memory/planning。
- 三类时间上下文的权威定义和入口标记是否完整。
- Markdown 本地链接目标是否存在。
- planning、development log 和 reviews 的季度目录、文件命名及总览登记。
- memory、规划总览和历史 log 是否越界复制需求队列或动态计划标题。
- 季度目录是否重新引入流水式开发计划。
- `memory.md` 和项目 Skill 是否超过加载预算。
- 项目 Skill 与已安装的全局镜像是否一致。
- Markdown、检查脚本、Makefile 和 pyproject 中的尾随空白与文件末尾换行。
- `git diff --check` 和 `git diff --cached --check`。

检查器输出 `context_summary` 和最终状态；出现 `ERROR` 时返回非零退出码。体量接近阈值或
尚未安装全局 Skill 时输出 `WARN`，但不阻塞普通项目验证。

## 人工补充检查

```bash
git status --short --branch
git log -1 --oneline --decorate
rg --files docs
```

自动检查负责结构正确，人工检查负责判断内容是否真实。以下语义目前仍需人工确认：

- memory 描述的阶段与当前代码是否一致。
- memory 的活跃需求是否与唯一 In Progress 需求一致，且没有复制 Planned 队列。
- architecture 是否混入临时实现流水账。
- log 中重复出现的规则是否应晋升到 architecture 或 AGENTS。
- review 中登记的风险是否已关闭或仍需跟踪。

## 检查项

### 1. 入口和单一事实源

- `docs/README.md` 两跳内可找到 memory、architecture、planning、reviews 和 runbooks。
- 根 `README.md` 只保留稳定介绍和入口，不维护动态需求状态或计划队列。
- 当前执行与验证基线只在 `docs/development/memory.md` 维护；需求状态和队列只在当前
  季度需求管理维护。

### 2. Memory

- 描述当前真实阶段、活跃需求、阻塞、恢复点和验证基线。
- 不复制完整未完成清单、Planned 队列或历史索引。
- 详细设计链接到 architecture，不复制稳定规则全文。
- 当前验证记录包含日期、OS、Python、Git 基线和实际命令。
- 超过约 150 行或无法在两分钟内扫完时立即瘦身。

### 2.1 时间上下文

- 过去式上下文包含日期、结果和证据，不冒充当前状态。
- 现在进行时上下文与实时 Git、runtime、当前需求状态一致。
- 未来规划上下文使用 Planned/Deferred 等显式状态，不宣称已经实现或验证。
- 任务开始时从未来规划进入现在进行时，结束时沉淀为过去式。
- 可复用规则已晋升到 architecture、AGENTS 或 runbooks，而不是只藏在历史日志中。

详细判定见 [Loot 时间上下文模型](../architecture/context/temporal-context-model-v0.1.md)。

### 3. Architecture、Log、Review 和 Planning

- architecture 记录稳定边界、契约、状态机、失败处理和验收标准。
- log 记录一次工作中的判断、证据、改动和验证。
- review 记录阶段结论、风险、缺口和复核清单。
- planning 使用当前季度总览和需求管理；需求管理独占状态、依赖和计划队列，不维护季度
  流水式开发计划。
- development log 的遗留判断标为历史快照，不使用“下一步”“后续”或“下一环节”标题。

### 4. Runbook 和 Project Skills

- 可重复命令真实执行过，或明确标记为计划。
- 新设备可以只根据 runbook 创建环境并重跑验证。
- 项目 Skill 是权威副本，全局 `$CODEX_HOME/skills` 只是镜像。
- 项目 Skill 通过 validator，且已安装镜像的哈希与项目副本一致。

### 5. AGENTS 和加载预算

- AGENTS 要求阅读的路径真实存在，硬约束与架构一致。
- 默认只加载入口、memory、架构索引和任务相关设计。
- 只有跨领域或系统级任务才加载完整系统架构，避免每次无差别读取大文档。
- 收尾动作覆盖 architecture、memory、log、review、runbook、AGENTS 和自动检查。

## 处理规则

- 入口、memory、AGENTS 或自动检查失败时，先修上下文再继续开发。
- architecture 与 implementation 不一致时，在同一变更中修正文档或实现。
- 同一规则在多个 log 里重复出现时，晋升到 architecture 或 AGENTS。
- 当前机器无法复现历史验证时，记录实际阻塞原因，不继续展示为“当前已通过”。
