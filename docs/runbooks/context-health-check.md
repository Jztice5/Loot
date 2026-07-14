# 上下文健康检查

## 使用时机

- 每次完成一段实质设计或实现后。
- 接手项目前感觉上下文不清楚时。
- 文档移动、重命名或新增重要约束后。
- 准备开始大规模实现前。

## 检查命令

```bash
git status --short --branch
rg --files docs
git diff --check
git diff --cached --check
```

## 检查项

### 1. 入口健康

- `docs/README.md` 存在。
- 能从 `docs/README.md` 两跳内找到 memory、architecture、planning、reviews 和 runbooks。
- 根 `README.md` 指向 `docs/README.md`。

### 2. Memory 健康

- `docs/development/memory.md` 描述当前真实阶段。
- 已验证命令和结果没有过期。
- 下一步和当前计划一致。
- 详细设计没有堆在 memory 里，而是链接到 architecture。

### 3. Architecture 健康

- `docs/architecture/README.md` 能说明每类设计归属。
- 系统级设计只讲稳定边界和原则。
- 组件级设计包含契约、状态机、幂等、失败处理和验收标准。

### 4. Log 健康

- 重要判断有过程记录。
- 过程记录说明为什么这样判断，不只是列出改动。
- 已晋升为架构规则的内容不再只藏在 log 里。
- 时间型日志位于正确的 `yyyy-Qn/`，季度总览文件名包含季度。

### 5. Review 健康

- 阶段结论、风险、缺口和复核清单在 `docs/reviews/` 可见。
- 未定事项能追溯到 architecture open questions 或 review memo。
- 评审位于对应季度目录，且季度评审总览文件名包含季度。

### 5.1 Planning 健康

- 当前季度具有 `规划总览-yyyy-Qn.md`、`需求管理-yyyy-Qn.md` 和
  `开发计划-yyyy-Qn.md`。
- `docs/planning/README.md` 只做跨季度导航，并指向当前季度。
- memory 和项目文档入口指向同一个当前季度。

### 6. Runbook 健康

- 可重复命令放在 `docs/runbooks/`。
- 命令真实执行过，或明确标记为计划。
- 运行说明和当前项目阶段一致。

### 7. AGENTS 健康

- `AGENTS.md` 中要求阅读的路径真实存在。
- 硬约束和当前架构文档一致。
- 收尾归档动作覆盖 architecture、memory、log、review、runbook 和 AGENTS。

## 处理规则

- 如果入口、memory 或 AGENTS 任一项失败，先修上下文再继续开发。
- 如果 architecture 和 implementation 不一致，同一变更中必须修正文档或实现。
- 如果同一规则在多个 log 里重复出现，晋升到 architecture 或 AGENTS。
