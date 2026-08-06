# REQ-0018 Crypto 历史数据集地基代码评审

## 评审范围

- 提交范围：`101736e..be07b86`。
- 历史 H1 分页、质量报告、Dataset Manifest、文件工件、CLI、测试与上下文收尾。
- 需求约束：[Crypto Historical Dataset Foundation Implementation Plan](../../planning/2026-Q3/REQ-0018-crypto-historical-dataset-foundation-plan.md)。
- 稳定设计：[Crypto 历史数据集与 Replay 数据基座 V0.1](../../architecture/testing/crypto-historical-dataset-replay-v0.1.md)。

## 总体结论

通过。最终独立复核未发现剩余 Critical 或 Important。生产短窗口 Provider Protocol 未被研究
能力污染，错误数据发布、内存对象绕过、目录替换和网络错误误分类均已用回归测试封闭。

该结论只表示历史输入地基具备确定性和可恢复性，不表示 V0.1/V0.2 已具有统计有效性。

## 初审发现与处理

| 级别 | 发现 | 处理 | 最终状态 |
|---|---|---|---|
| Important | 只检查连续 `closed_at`，伪 H1 时长可通过 | 增加一小时时长和 UTC 整点 `opened_at` 质量字段与门禁 | Addressed |
| Important | 直接构造 `HistoricalBarDataset` 可绕过 Builder 后写入 | Writer 创建目录前重新从 bars 推导并比对完整 Dataset | Addressed |
| Important | Loader 未绑定目录名与 manifest dataset_id | 强制目录名等于 manifest dataset_id | Addressed |
| Minor | CLI 输出任意内部异常类名 | 映射为固定 DatasetQuality/Provider/Artifact/Unexpected 类别 | Addressed |
| Minor | 错误路径测试不足 | 增加网络、错误码、未闭合、倒置区间、绕过、缺失文件与目录替换测试 | Addressed |

## Scoped Re-review

第一次复核确认前三个 Important 已关闭，但发现 `URLError` 继承 `OSError`，会被 CLI 误归类
为 Artifact。最终修复：

- OKX Provider 请求统一包装网络、编码和 JSON 解析错误为 `CryptoProviderError`。
- CLI 在 Artifact `OSError` 分支前捕获 `URLError` / `TimeoutError`。
- Provider 与 CLI 各增加真实网络异常分类回归测试。

第二次 scoped re-review 判定该 finding `ADDRESSED`，未发现修复 diff 引入的新 Critical 或
Important。

## 验证证据

环境：Windows PowerShell，Codex bundled Python 3.12.13，日期 2026-08-06。

- 主流程全量测试：`160 passed in 11.93s`。
- 独立 reviewer 复验：`160 passed in 13.33s`。
- `scripts/check_context.py`：通过。
- `git diff --check`：通过。
- 真实连续 365 天数据集：`8760` 根，强化契约下重新加载通过。

## 残余边界

- 本地 JSON/JSONL 是当前研究工件，不是 PostgreSQL 长期行情事实表。
- 尚未实现 ReplayRun、Outcome Label、MFE/MAE、1R/2R 和 V0.1 基线报告。
- 一年数据通过完整性检查不等于现有突破规则具备准确性或收益能力。

## 一句话结论

历史输入地基已经通过代码、真实数据和独立审查三重验证，可以进入 Replay 与结果标签设计。
