# 2026-07-21 REQ-0013 Crypto Run-Once 持久化闭环

## 背景

- Crypto Provider、PreFilter、决策授权链和 PostgreSQL Repository 已分别可用，但没有正式
  应用入口调用它们。
- 既有集成测试结束后会清理数据，因此 DBX 中无法观察进程退出后保留的完整业务链。

## 判断过程

- 本轮只增加薄应用层，不改变 PreFilter、Policy Gate、Signal State Machine 和 Repository
  的事实所有权。
- `demo` 必须稳定产生 LONG Golden Case；`live` 没有 Candidate 时必须正常结束，不能为了
  展示数据库记录伪造信号。
- Signal 初始化放到 Candidate 之后，避免真实行情无突破时堆积 OBSERVING 投影。
- 不新增行情表和 migration；Inbox 只保存完整 Candidate 消息指纹，不保存原始 payload。
- 四个既有事务边界保持独立，中断后保留已提交事实供诊断，不做删除补偿。

## 改动

- 新增 `src/loot/application/crypto_run_once.py`，定义命令、结果、demo Provider 和应用服务。
- 新增 `scripts/run_crypto_once.py`，只加载 `LOOT_TEST_DATABASE_URL`，写入前复核数据库名，
  输出不含凭据的 JSON 摘要。
- 新增 4 个应用单元测试和 1 个真实 PostgreSQL 集成测试。
- 新增 Run-Once 架构设计、实施计划和本地运行说明。
- 修正 Windows context check 调用 Git 时依赖系统 GBK 解码的问题，显式按 UTF-8 读取并在
  非法字节处安全替换，避免后台 reader thread 异常污染检查结果。

## 验证

- `& .\.venv\Scripts\python.exe -m pytest -q tests\unit\application\test_crypto_run_once.py`：
  4 passed。
- `& .\.venv\Scripts\python.exe -m pytest -q tests\integration\test_crypto_run_once.py`：
  1 passed。
- `& .\.venv\Scripts\python.exe -m pytest -q`：90 passed。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts migrations`：通过。
- PyCharm 文件检查：应用服务、CLI 和单元测试无问题；项目构建成功。
- `& .\.venv\Scripts\python.exe scripts\check_context.py`：通过，67 个 Markdown、164 个
  本地链接，项目 Skill 与本机镜像一致，且不再出现后台解码异常。
- PyCharm 正式运行 demo：退出码 0，`run_id=64fe5b0c-adc2-4504-86aa-a93d25360c77`，
  `signal_id=5e5b4931-5de9-5d09-94d8-317ce8d0415b`，结果为 `LONG / ARMED`。
- DBX 只读复核 `loot_test`：Inbox、Evidence、Signal、Proposal、Proposal-Evidence、Evaluation、
  Ticket、Transition 和 Consumption 各 1 条，Outbox 5 条；Policy 为 `APPROVED`，迁移为
  `OBSERVING -> ARMED`。该手工 demo 数据未清理。

## 历史快照

- 原始 MarketBar、MarketSnapshot 和 Candidate payload 尚未持久化，当前事实链不能独立重放
  完整行情窗口。
- Run-Once 是同步单次命令，不包含调度、跨事务恢复、Alert 或 Replay。
