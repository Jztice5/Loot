# Crypto 历史数据集采集 Runbook

## 用途

为 REQ-0018 采集并发布内容寻址的 OKX `BTC-USDT` H1 历史数据集。命令只访问公共行情，
不读取账户、不需要 API Key、不写 PostgreSQL。

稳定设计：[Crypto 历史数据集与 Replay 数据基座 V0.1](../architecture/testing/crypto-historical-dataset-replay-v0.1.md)。

## 前置条件

在项目根目录执行，并已按项目方式创建 `.venv`、安装当前包及 dev 依赖。目标时间必须带时区，
内部会归一化为 UTC，且首尾都必须落在整点 H1 闭合边界。

## 采集最近 24 根已闭合 H1

```powershell
$end = (Get-Date).ToUniversalTime().AddHours(-1)
$end = [datetime]::new($end.Year, $end.Month, $end.Day, $end.Hour, 0, 0, [DateTimeKind]::Utc)
$start = $end.AddHours(-23)

.venv\Scripts\python.exe scripts\fetch_crypto_history.py `
  --start-closed-at $start.ToString('o') `
  --end-closed-at $end.ToString('o') `
  --output-dir data/replay
```

成功时返回单行 JSON，关键字段包括：

- `status=COMPLETED`
- `dataset_id`
- `content_hash`
- `bar_count=24`
- `dataset_directory`

## 采集连续 365 天 H1

首尾包含在区间内，因此 365 天使用 `365 * 24 = 8760` 根：

```powershell
$end = (Get-Date).ToUniversalTime().AddHours(-1)
$end = [datetime]::new($end.Year, $end.Month, $end.Day, $end.Hour, 0, 0, [DateTimeKind]::Utc)
$start = $end.AddHours(-(365 * 24 - 1))

.venv\Scripts\python.exe scripts\fetch_crypto_history.py `
  --start-closed-at $start.ToString('o') `
  --end-closed-at $end.ToString('o') `
  --output-dir data/replay
```

OKX 历史接口单页最大 300 根，CLI 默认每页间隔 0.11 秒。不要通过降低间隔绕过 Provider
限流；遇到暂时性网络错误时重新执行相同命令即可。

## 工件结构

```text
data/replay/<dataset_id>/
  manifest.json
  quality-report.json
  bars.jsonl
```

`data/replay/` 是本地生成物并已加入 `.gitignore`。同区间同内容重试得到相同 `dataset_id`；
如果 OKX 修正了历史行情事实，内容摘要和 `dataset_id` 会变化，旧数据集不会被静默覆盖。

## 重新加载验证

```powershell
$dataset = Get-ChildItem data/replay -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.venv\Scripts\python.exe -c "from loot.replay import load_historical_dataset; from pathlib import Path; d=load_historical_dataset(Path(r'$($dataset.FullName)')); print(d.manifest.model_dump_json())"
```

加载过程会重新运行 `MarketBar` 契约、连续性检查和内容摘要。任一文件缺失、存在空行、K 线被
修改或 manifest 与实际内容不一致时，验证失败。

## 常见失败

| reason / error_type | 含义 | 处理 |
|---|---|---|
| `INVALID_PAGE_LIMIT` | page limit 不在 1 到 300 | 恢复默认值或传合法值 |
| `INVALID_PROVIDER_CONFIGURATION` | timeout 非正数或页间隔为负 | 修正 CLI 参数 |
| `CryptoTargetWindowUnavailableError` | OKX 未完整覆盖目标区间 | 稍后重试；持续失败时缩小区间定位缺口 |
| `DATASET_QUALITY_FAILED` | 存在缺失、重复、未闭合或 identity 问题 | 根据输出计数检查区间和 Provider 数据 |
| `HistoricalDatasetArtifactError` | 本地工件缺失、损坏或被修改 | 删除该损坏目录后重新采集，不手工修 manifest |
