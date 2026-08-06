# REQ-0018 Crypto Historical Dataset Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可重复拉取、校验、保存和恢复 BTC H1 历史数据的首个 REQ-0018 可验收切片。

**Architecture:** 保留生产短窗口 Provider Protocol，新增 Replay 数据集契约和 Builder；OKX
Provider 以独立方法实现向过去分页，输出仍为生产 `MarketBar`。只有完整性报告通过的数据才能
生成内容寻址 manifest，Replay 后续只读取工件，不直接访问网络。

**Tech Stack:** Python 3.12、Pydantic 2、标准库 urllib/json/pathlib、pytest/unittest。

## Global Constraints

- V0.1 只实现 Crypto BTC-USDT H1，不实现其他市场、Agent、Outcome Label 或 V0.2 规则。
- 目标区间使用包含首尾的 UTC 整点 `start_bar_closed_at` / `end_bar_closed_at`。
- OKX 单页最大 300 根，默认页间隔至少 0.11 秒；测试必须注入 HTTP 与 sleep，不访问外网。
- Dataset identity 必须绑定完整有序行情内容，忽略采集时钟和 manifest 生成时钟。
- 缺失、重复、未闭合或身份不一致的数据不能生成通过状态 manifest。
- 生产 `CryptoMarketDataProvider` Protocol 不增加历史研究方法。
- Python 核心类和方法遵守项目业务 docstring 与调用链注释约束。

---

### Task 1: 数据集契约、质量报告与确定性身份

**Files:**
- Create: `src/loot/contracts/replay.py`
- Modify: `src/loot/contracts/__init__.py`
- Create: `src/loot/replay/__init__.py`
- Create: `src/loot/replay/dataset.py`
- Create: `tests/unit/replay/__init__.py`
- Create: `tests/unit/replay/test_dataset.py`

**Interfaces:**
- Consumes: `MarketBar`, `MarketSnapshot`, `Market`, `Timeframe`。
- Produces: `HistoricalDatasetQualityReport`、`HistoricalDatasetManifest`、
  `HistoricalBarDataset.build(...)`。

- [ ] **Step 1: 写完整区间的失败测试**

```python
dataset = HistoricalBarDataset.build(
    provider="okx.public_rest",
    market=Market.CRYPTO,
    instrument_id=instrument_id,
    timeframe=Timeframe.H1,
    start_bar_closed_at=t0 + timedelta(hours=1),
    end_bar_closed_at=t0 + timedelta(hours=3),
    bars=(bar0, bar1, bar2),
    generated_at=t0 + timedelta(days=1),
)
assert dataset.quality_report.passed is True
assert dataset.manifest.expected_bar_count == 3
```

- [ ] **Step 2: 运行测试并确认因 `loot.replay.dataset` 不存在而失败**

Run: `.venv\Scripts\python.exe -m pytest -q tests\unit\replay\test_dataset.py`
Expected: collection error 或 import error，明确缺失新接口。

- [ ] **Step 3: 实现最小契约与 Builder**

实现内容：质量报告收集预期/实际数量、缺失时间、重复事件、重复闭合时间、未闭合和身份问题；
通过后复用 `MarketSnapshot.from_bars` 计算内容摘要，并由
`crypto.market-bars.v1:{provider}:{instrument_id}:{timeframe}:{start}:{end}:{hash}` 生成 UUIDv5。

- [ ] **Step 4: 增加并运行边界测试**

测试分别覆盖缺失、重复、未闭合、identity 不一致、生成时钟变化但 identity 不变、行情内容变化
后 identity 改变。Run 同 Step 2，Expected: 全部 PASS。

- [ ] **Step 5: 提交 Task 1**

提交范围只包含 Task 1 文件，使用仓库结构化中文提交模板。

### Task 2: OKX 历史 H1 分页采集

**Files:**
- Modify: `src/loot/domains/crypto/market_data.py`
- Modify: `tests/unit/domains/crypto/test_market_data.py`

**Interfaces:**
- Consumes: `Instrument`、`Timeframe.H1`、UTC 闭合区间。
- Produces: `OkxRestCryptoProvider.fetch_historical_bars(...) -> tuple[MarketBar, ...]`。

- [ ] **Step 1: 写倒序两页采集的失败测试**

测试 HTTP 替身先返回较新的两根，再根据第二次 URL 的 `after=<oldest_open_ms>` 返回更早两根；
断言最终结果升序、精确裁剪请求区间，并断言 sleep 只发生在需要下一页时。

- [ ] **Step 2: 运行目标测试并确认方法不存在**

Run: `.venv\Scripts\python.exe -m pytest -q tests\unit\domains\crypto\test_market_data.py -k historical_range`
Expected: FAIL，原因是 `fetch_historical_bars` 尚未实现。

- [ ] **Step 3: 实现最小历史分页方法**

校验 OKX/CRYPTO/H1、UTC 整点和首尾顺序；每页调用 `history-candles`，使用 `after` 向过去推进，
解析后仅保留已闭合且位于包含区间内的 K 线，以 provider_event_id 去重，游标不前进时失败。

- [ ] **Step 4: 增加错误路径并运行 Provider 全量单测**

覆盖 Provider 错误、空页、未覆盖开始时间、重复页导致游标不前进和非法区间。
Run: `.venv\Scripts\python.exe -m pytest -q tests\unit\domains\crypto\test_market_data.py`
Expected: 全部 PASS。

- [ ] **Step 5: 提交 Task 2**

提交范围只包含 Task 2 文件，使用仓库结构化中文提交模板。

### Task 3: 数据集文件工件与采集 CLI

**Files:**
- Modify: `src/loot/replay/dataset.py`
- Modify: `src/loot/replay/__init__.py`
- Create: `scripts/fetch_crypto_history.py`
- Modify: `.gitignore`
- Modify: `tests/unit/replay/test_dataset.py`
- Create: `tests/unit/replay/test_fetch_crypto_history_cli.py`
- Create: `docs/runbooks/crypto-historical-dataset.md`

**Interfaces:**
- Consumes: `HistoricalBarDataset`、`OkxRestCryptoProvider.fetch_historical_bars`。
- Produces: `write_historical_dataset(...)`、`load_historical_dataset(...)` 和 CLI 摘要。

- [ ] **Step 1: 写工件往返的失败测试**

用 `tmp_path` 写入三根 K 线，断言目录包含 `manifest.json`、`quality-report.json`、`bars.jsonl`；
重新加载后 manifest、quality report 和 bars 与原对象相同。篡改 bars 后必须因摘要不一致失败。

- [ ] **Step 2: 运行测试并确认写入/读取接口不存在**

Run: `.venv\Scripts\python.exe -m pytest -q tests\unit\replay\test_dataset.py -k artifact`
Expected: FAIL，原因是工件接口尚未实现。

- [ ] **Step 3: 实现原子文件工件**

使用同目录临时文件和 `Path.replace` 写入；JSON 使用 Pydantic JSON mode 与稳定键排序；加载时
重新构造 MarketBar、质量报告和 manifest，并重新计算完整性与 content hash。

- [ ] **Step 4: 先写再实现 CLI 测试**

测试注入 Provider 后断言默认标的 `BTC-USDT`、周期 H1、输出目录和成功 JSON 摘要；质量失败时
返回非零。CLI 参数必须显式接收 `--start-closed-at`、`--end-closed-at` 和 `--output-dir`。

- [ ] **Step 5: 更新 runbook 并运行切片测试**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\unit\replay tests\unit\domains\crypto\test_market_data.py
.venv\Scripts\python.exe scripts\check_context.py
git diff --check
```

Expected: 测试、context check 和 diff check 全部通过。

- [ ] **Step 6: 执行真实小区间 smoke**

先抓取连续 24 根已收盘 BTC-USDT H1，确认质量通过且加载后 identity 不变；网络不可用时在
memory 中记录为明确阻塞，不伪造通过结果。

- [ ] **Step 7: 提交 Task 3**

提交代码、测试、runbook、架构实现状态和上下文收尾，排除 `.idea` 与 `data/replay` 工件。
