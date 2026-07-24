# 2026-07-14 上下文框架长期加固与 macOS 适配

## 背景

对当前上下文框架做长期 vibe coding 审阅后，确认目录分层和季度归档方向成立，但发现四个
会在长期开发中放大的缺口：根 README 与 memory 状态漂移、验证环境不可复现、AGENTS
强制加载上下文偏重，以及链接和季度结构只靠人工检查。

## 目标

- 让动态状态只有一个权威来源。
- 降低普通任务的基础上下文加载量。
- 让新 macOS 环境可从仓库命令完成初始化和复验。
- 把重复执行的上下文健康检查固化为仓库脚本。
- 保持项目 Skill 为权威副本，并同步全局 Codex 镜像。

## 判断过程

- 根 README 曾把已完成的 REQ-0009 写成下一步，说明动态事实不能靠多文件同步。
- memory 记录 41 tests OK，但当前 `.venv` 缺少 `pydantic`，说明历史结果缺少环境来源。
- 原 AGENTS 每次要求完整读取 722 行系统架构，普通组件任务承担了不必要加载成本。
- 原健康检查要求做 Markdown 链接扫描，却没有保存可复现命令。
- `.DS_Store` 未被忽略，导致健康检查长期出现无意义工作区噪声。

## 改动

- 根 README 只保留稳定介绍、文档入口和 macOS 快速开始。
- AGENTS 明确 memory/planning 的事实归属，并按任务加载相关架构文档。
- 新增 `Makefile`，提供 `setup`、`test`、`compile`、`context-check`、`check` 和 `run`。
- 新增标准库脚本 `scripts/check_context.py`，检查入口、链接、季度命名、体量预算、
  Skill 镜像和 Git 空白错误。
- `local-run.md` 增加 macOS、Linux、Windows 的初始化与验证命令。
- `pyproject.toml` 的 dev dependencies 增加 PyYAML，确保 Skill validator 在新环境可用。
- `.gitignore` 增加 `.DS_Store`。
- 瘦身 memory，把稳定架构规则改为链接，仅保留活跃差异。
- 更新项目 `vibe-context-manager`，加入单一事实源、验证来源、加载预算和自动检查规则。

## 验证

环境：macOS Apple Silicon，Python 3.13.9，Git 基线 `fadb523`。

```bash
make setup
make check
.venv/bin/python main.py
```

结果：

- editable install 和 dev dependencies 安装成功。
- `make context-check` 通过。
- `src`、`tests` 和 `scripts` 的 `compileall` 通过。
- `Ran 41 tests`，`OK`。
- `main.py` 输出 `Hi, PyCharm`。
- 项目 Skill 和全局镜像 validator 通过，SHA-256 一致。

## 当时遗留事项（历史快照）

- 当前业务优先级仍是 REQ-0006，再推进 REQ-0005。
- 进入 2026-Q4 前做一次 carryover 演练，验证跨季度规则。
- 如果自动检查出现需要人工反复判断的新模式，再扩展脚本，不预先引入复杂文档平台。
