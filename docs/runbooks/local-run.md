# 本地运行说明

## 当前状态

当前仓库已建立初始 Python 项目骨架、核心 contracts、Signal State Machine 和 Crypto 行情 Provider。`main.py` 仍是 PyCharm 示例脚本，正式 API、worker 和数据库尚未启动。

## 运行示例脚本

```bash
py main.py
```

预期输出：

```text
Hi, PyCharm
```

## 注意事项

- 当前 Windows 环境中 `python` 可能先命中 WindowsApps shim，建议暂时使用 `py`。
- 当前 pytest 是可选开发依赖；Phase 0 契约测试先使用标准库 `unittest`。
- 正式 API、worker、数据库建立后，本文件需要继续补启动方式。

## 运行契约测试

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
py -3.12 -m unittest discover -s tests -p 'test_*.py'
```

预期输出包含：

```text
Ran 26 tests
OK
```

## 编译检查

```bash
py -3.12 -m compileall src tests
```

## OKX 公共行情 Smoke

该命令只读取 OKX public REST K 线，不需要 API key，不访问账户，不下单。

```powershell
$env:PYTHONPATH='D:\my-projects\Loot\src'
@'
from uuid import uuid4
from loot.contracts import Instrument, InstrumentStatus, InstrumentType, Market, Timeframe
from loot.domains.crypto import OkxRestCryptoProvider

instrument = Instrument(
    instrument_id=uuid4(),
    market=Market.CRYPTO,
    venue='OKX',
    symbol='BTC-USDT',
    instrument_type=InstrumentType.SPOT,
    quote_currency='USDT',
    timezone='UTC',
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
    snapshot.bars[-1].symbol,
    snapshot.bars[-1].close_price,
)
'@ | py -3.12 -
```

已验证输出示例：

```text
okx.public_rest 2 BTC-USDT <close_price>
```
