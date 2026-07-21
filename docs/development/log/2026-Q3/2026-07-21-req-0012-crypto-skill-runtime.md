# 2026-07-21 REQ-0012 Crypto Skill Runtime

## 背景

- Candidate、Evidence 和 Proposal 已经稳定，但项目还没有统一的 Skill 版本、市场权限、
  输入输出类型、超时和审计边界。
- Agent 接入前必须先保证它只能选择显式注册且已授权的 Skill。

## 判断过程

- V0.1 只实现平台运行时，不创建 US Equity 或 A-Share 业务 Skill。
- Registry 必须精确解析 `skill_id + version`，禁止“自动最新版本”破坏 Replay。
- capability 和市场校验必须发生在 handler 前，拒绝同样要保留审计记录。
- Python 线程无法安全强杀；因此 V0.1 timeout 是响应截止线，handler 必须是无副作用纯分析，
  迟到输出会被丢弃。不可信 Skill 的进程隔离留到独立需求。

## 改动

- 新增 `src/loot/runtime`，包含 manifest、registry、executor、运行记录和内存审计。
- 增加 manifest 类型声明与实际定义一致性校验、精确版本唯一注册和 capability allowlist。
- 增加成功、拒绝、类型错误、handler 异常、超时和重复注册测试。
- 未新增数据库表，未接 Agent、LLM、网络、Redis 或 Alert。

## 验证

- `& .\.venv\Scripts\python.exe -m pytest -q tests\unit\runtime\test_skill_runtime.py`：7 passed。
- `& .\.venv\Scripts\python.exe -m pytest -q`：85 passed。
- `& .\.venv\Scripts\python.exe -m compileall -q src tests scripts migrations`：通过。
- PyCharm 对新增测试无问题；核心 Runtime 只保留一项有意的 broad-exception 弱提示，用于把
  任意 handler 异常转换为结构化 `FAILED` 审计，异常文本不会泄露。

## 历史快照

- SkillRun 当前仅保存在内存，PostgreSQL 事实持久化尚未设计。
- 线程 timeout 不等于进程隔离；当前只允许受信、无副作用的确定性 Skill。
