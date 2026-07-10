# Loot 设计分层校对备忘录

## 1. 校对范围

- 参考项目：`D:\YLWX-project\PythonProject\docs`。
- 当前项目：`D:\my-projects\Loot`。
- 范围：Loot 设计文档目录分层、入口索引、宏观设计和闭环设计归属。

## 2. 当前总体结论

Loot 不适合把所有设计都放进一个 `technical-design` 目录。更适合沿用智能客服项目的分层方式：

```text
docs/
  architecture/   稳定架构设计
  development/    开发记忆和过程记录
  planning/       每日计划和项目管理记录
  reviews/        评审、校对和阶段结论
  runbooks/       本地运行、测试、排障手册
```

这样可以把“长期架构判断”和“当天推进记录”分开，也方便后续 Codex 每次接手时快速恢复上下文。

## 3. 已对齐的关键设计点

### 3.1 系统级设计单独存放

系统宏观架构进入 `docs/architecture/system/`，只描述系统边界、核心原则、P1 范围和演进路线。

### 3.2 功能闭环设计单独存放

自选与持仓信号监控闭环进入 `docs/architecture/signal-monitoring/`，作为第一条组件级/功能级设计文档。

### 3.3 过程记忆不污染架构设计

当前真实状态、下一步、已验证和未完成事项进入 `docs/development/memory.md`。

### 3.4 过程日志保留判断依据

后续每个大功能点用 `docs/development/log/TEMPLATE.md` 记录背景、目标、判断过程、改动点和验证结果。

## 4. 当前仍需继续校对的关键缺口

- P1 最小闭环范围仍需继续收窄。
- Signal State Machine 的“统一引擎”和“市场 TransitionPolicy”职责需要在实现前再次钉死。
- contracts 还没有独立设计文档。
- 当前代码仍是 PyCharm 示例，尚无项目骨架和测试入口。

## 5. 后续每次改代码时的复核清单

### A. 是否仍符合三市场独立边界

- `crypto`、`us_equity`、`a_share` 不能直接互相依赖。
- 跨领域共享内容只能放在 contracts、shared 或平台公开接口。

### B. Agent 是否仍然没有最终写权限

- Agent 只能编排 Skill 和汇总 Evidence。
- Signal 状态必须通过 Policy Gate 和 State Machine。

### C. 幂等是否被保留

- PositionEvent、DecisionTicket、SignalTransition、Alert 都要有可验证的幂等键或唯一约束。

### D. 文档是否同步

- API、事件、表结构、状态迁移变化必须同步更新 architecture 或 development log。

## 6. 一句话结论

Loot 的文档体系应该像智能客服项目一样，把稳定架构、开发记忆、过程记录、评审结论和运行手册分层存放；下一步应在这个骨架上先收敛 P1 最小可运行闭环。
