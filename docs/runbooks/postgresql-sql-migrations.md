# PostgreSQL SQL Migration 操作手册

## 适用范围

本手册用于通过 DBX 执行 `migrations/versions/` 下的版本化 PostgreSQL SQL 文件。
当前版本按顺序为：

- `20260716_0001_crypto_decision_persistence.sql`
- `20260727_0002_crypto_watchlist_monitoring.sql`

SQL migration 只负责数据库结构；应用运行和集成测试始终使用非 DDL 角色 `loot_app`。

## 角色与执行顺序

| 环节 | 数据库 | 角色 |
|---|---|---|
| 首次验证 | `loot_test` | `loot_migrator` |
| 集成测试 | `loot_test` | `loot_app` |
| 本地开发运行 | 优先 `loot_test` | `loot_app` |

禁止使用 `postgres` 超级用户作为应用连接。密码只保存在 DBX、本机用户级配置或环境变量中，不进入
仓库、日志、截图或测试 fixture。

## 在 DBX 执行

1. 使用 `loot_migrator` 连接目标数据库，首次必须选择 `loot_test`。
2. 打开目标版本 `.sql` 文件并一次执行完整文件，不拆开 `BEGIN` 和 `COMMIT`。
3. 确认事务成功后，使用 `loot_app` 专用连接重新打开 `loot_test`。
4. 验证 `current_database()`、`current_user`、`search_path` 和 schema 权限。
5. 验证当前 migration 声明的表、索引和约束均存在。执行 0002 后，`loot` schema 应在
   原 10 张决策链表之外新增 `instruments`、`watch_items` 和 `monitoring_subscriptions`。

权限探针：

```sql
SELECT
    current_database(),
    current_user,
    session_user,
    current_setting('search_path'),
    has_schema_privilege(current_user, 'loot', 'USAGE') AS schema_usage,
    has_schema_privilege(current_user, 'loot', 'CREATE') AS schema_create;
```

预期：数据库为目标库，用户为 `loot_app`，`schema_usage=true`，`schema_create=false`。

## 集成测试

Windows PowerShell：

```powershell
& .\scripts\configure_test_database.ps1
& .\.venv\Scripts\python.exe -m pytest -q
```

脚本将 DSN 写入 `%USERPROFILE%\.loot\database.env`，仅允许配置 `loot_test`。对于 CI 或一次性
覆盖，可设置 `LOOT_TEST_DATABASE_URL`；环境变量优先于用户级配置。

macOS/Linux：

```bash
export LOOT_TEST_DATABASE_URL='postgresql+psycopg://loot_app:<password>@<host>:5432/loot_test'
.venv/bin/python -m pytest -q
```

集成测试只允许访问 `loot_test`，测试代码会拒绝其他数据库名。测试完成后必须确认测试
专用事实已经清理，不能把测试清理逻辑用于 `loot_dev`。

## 回退原则

建表 SQL 不内置破坏性 downgrade。空测试库执行失败时，先保留错误和事务状态，修复 SQL
后重新创建测试 schema 或数据库；已承载业务数据的环境必须使用新的前向修复 migration，
禁止直接复制 DROP 语句处理。
