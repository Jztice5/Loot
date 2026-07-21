# 本地运行说明

## 当前状态

当前仓库已建立 Python 项目骨架、核心 contracts、Signal State Machine、Crypto 行情
Provider 和 PostgreSQL 决策持久化基线。正式 API、worker 尚未启动，`main.py` 仍是
示例入口。

项目要求 Python 3.12+，依赖以 `pyproject.toml` 为准。首次克隆、切换设备或依赖变化后，
必须先执行环境初始化，不能直接复用旧 `.venv` 的历史状态。

## macOS

### 初始化

```bash
python3 --version
make setup
```

`make setup` 会创建 `.venv`，升级 pip，并以 editable 模式安装项目及开发依赖。

### 完整检查

```bash
make check
```

该命令依次执行：

- 上下文健康检查。
- `compileall`。
- 全部 `unittest`。

### 单独执行

```bash
make context-check
make compile
make test
make run
```

不用 Makefile 时，对应命令为：

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/check_context.py
.venv/bin/python -m compileall -q src tests scripts
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python main.py
```

## Linux

Linux 与 macOS 使用相同的 `make setup` 和 `make check`。如果系统尚未安装 `make`，可直接
执行上一节列出的 `.venv/bin/python` 命令。

## Windows PowerShell

### 初始化

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 验证

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
& .\.venv\Scripts\python.exe scripts\check_context.py
& .\.venv\Scripts\python.exe -m compileall -q src tests scripts
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe main.py
```

### 配置 PostgreSQL 集成测试

首次或本地口令轮换后，运行以下命令并按提示输入 `loot_app` 的 `loot_test` 口令：

```powershell
& .\scripts\configure_test_database.ps1
```

该脚本只把 DSN 写入 `%USERPROFILE%\.loot\database.env`，不会写入仓库或 PowerShell 历史。
CI 和临时覆盖仍可使用 `LOOT_TEST_DATABASE_URL` 环境变量，且环境变量优先于用户级配置。

## 预期基线

未配置 PostgreSQL 测试连接时，当前预期基线为：

```text
78 passed, 7 skipped
```

配置 `%USERPROFILE%\.loot\database.env` 或 `LOOT_TEST_DATABASE_URL` 并可连接 `loot_test` 后，
当前预期基线为 `85 passed`。数据库初始化和权限验证见
[PostgreSQL SQL Migration 操作手册](postgresql-sql-migrations.md)。

`main.py` 的当前预期输出：

```text
Hi, PyCharm
```

实际通过结果必须写入 `docs/development/memory.md`，同时记录日期、操作系统、Python
版本、Git 基线和实际命令。旧设备上的历史通过结果不能替代当前环境复验。

## OKX 公共行情 Smoke

该命令只读取 OKX public REST K 线，不需要 API key，不访问账户，不下单：

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
from uuid import uuid4

from loot.contracts import Instrument, InstrumentStatus, InstrumentType, Market, Timeframe
from loot.domains.crypto import OkxRestCryptoProvider

instrument = Instrument(
    instrument_id=uuid4(),
    market=Market.CRYPTO,
    venue="OKX",
    symbol="BTC-USDT",
    instrument_type=InstrumentType.SPOT,
    quote_currency="USDT",
    timezone="UTC",
    price_scale=2,
    status=InstrumentStatus.ACTIVE,
)
snapshot = OkxRestCryptoProvider(timeout_seconds=10.0).fetch_recent_bars(
    instrument,
    Timeframe.H1,
    limit=2,
)
print(
    snapshot.source_provider,
    len(snapshot.bars),
    snapshot.latest_bar.symbol,
    snapshot.latest_bar.close_price,
    snapshot.latest_bar.is_closed,
)
PY
```

预期格式：

```text
okx.public_rest 2 BTC-USDT <close_price> True
```

如果网络、代理或 OKX 服务不可用，记录为外部 smoke 未通过；不能把它与本地单元测试失败
混为一谈。
