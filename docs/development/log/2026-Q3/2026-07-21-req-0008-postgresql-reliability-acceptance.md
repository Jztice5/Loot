# 2026-07-21 REQ-0008 PostgreSQL 可靠性验收

## 背景

- REQ-0008 已完成 SQL migration、事实仓库和 Crypto 持久化工作流，需要用真实 `loot_test`
  数据库验证并发、事务和恢复语义。
- 本机 IDE 需要可重复读取测试连接，同时不得把凭据写入仓库或测试输出。

## 验收过程

- 使用 `loot_app` 连接 `loot_test`，确认 `loot` schema 中 10 张业务表、70 个显式业务约束、
  31 个索引（含 2 个 partial index）存在。
- 确认运行角色具有业务表 DML 权限，但没有 schema CREATE 权限。
- 新增真实 PostgreSQL 集成测试，覆盖 Signal 并发初始化、Policy stale attempt、Ticket 乐观锁
  冲突、Outbox 恢复、Outbox 冲突回滚和重启后的重复消费。
- 新增用户级配置加载器和 PowerShell 配置脚本。环境变量优先，默认配置位于
  `%USERPROFILE%\.loot\database.env`，该文件不属于仓库。

## 验证

- 2026-07-21，Windows PowerShell，Python 3.12.13：7 个 PostgreSQL 集成测试通过。
- 同一环境执行 `& .\.venv\Scripts\python.exe -m pytest -q`：`78 passed in 5.42s`。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts migrations`：通过。
- `& .\.venv\Scripts\python.exe scripts\check_context.py`：通过（59 个 Markdown、148 个本地链接）。

## 结论

- REQ-0008 的验收边界为 `loot_test`，需求状态已转为 Done。
- `loot_dev` 未执行 migration；其 rollout/deployment 工作未被视为本需求的剩余项。
- `loot` schema owner 为 `loot_migrator`，而 10 张既有业务表 owner 仍为 `postgres`。该差异当前
  不影响 `loot_app` 的 DML 验收，保留给后续数据库运维治理。
