# 2026-07-14 上下文文档季度化整理

## 背景

Loot 的 architecture、development log、planning、reviews 和 runbooks 已经形成完整
上下文层，但时间型文档开始持续增长。所有文件平铺在目录根部，会让查询、季度回顾和
后续归档越来越依赖文件名猜测。

## 判断

不能把整个 docs 按季度切开。architecture、memory 和 runbook 是稳定知识入口，按季度
拆分会让新 Codex 难以判断哪一版有效。真正需要季度化的是具有明确发生时间的过程资料：

- development log
- planning
- reviews

仅使用季度目录仍不够。搜索结果如果脱离父目录展示，`README.md`、`需求管理.md` 和
`开发计划.md` 仍然无法直接判断季度，因此季度总览、需求管理和开发计划的文件名也必须
显式包含 `yyyy-Qn`。

## 调整

- 2026 年 7 月日志迁入 `docs/development/log/2026-Q3/`。
- 2026 年 7 月评审迁入 `docs/reviews/2026-Q3/`。
- Q3 规划迁入 `docs/planning/2026-Q3/`。
- 新增 `开发过程总览-2026-Q3.md`、`评审记录总览-2026-Q3.md` 和
  `规划总览-2026-Q3.md`。
- 需求与计划重命名为 `需求管理-2026-Q3.md`、`开发计划-2026-Q3.md`。
- 三个时间型目录根 `README.md` 只做跨季度导航。
- 更新 docs 入口、memory、AGENTS、runbook 和全局 `vibe-context-manager`。
- 将 `vibe-context-manager` 权威副本纳入 `docs/skills/`，并提供多端同步 runbook。

## 验证

- 扫描全部 Markdown 本地链接，确保移动后没有失效路径。
- 搜索旧 planning、review 和 log 路径，确保不再残留过期引用。
- 执行 `git diff --check`。

## 当时遗留事项（历史快照）

进入 2026-Q4 时创建新的季度目录和带季度名的总览文档。未完成需求写入 Q4 需求管理并
标注来源为 2026-Q3，Q3 文档转为只读历史。
