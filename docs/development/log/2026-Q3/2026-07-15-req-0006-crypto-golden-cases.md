# REQ-0006 Crypto Golden Cases V0.1

## 背景

Crypto 行情 Provider 和 Snapshot 不变量已经稳定，但 PreFilter 尚无可执行的产品预期。
直接编码会让“什么算突破”被实现细节决定，因此先固定 Golden Case。

## 业务判断

- 使用最新已收盘 K 线作为 trigger bar。
- 使用 trigger bar 之前 3 根已收盘 K 线作为 reference window。
- 收盘价严格高于 reference_high 才生成 LONG。
- 收盘价严格低于 reference_low 才生成 SHORT。
- 等于边界、只有影线越界、历史不足或最新 K 线未收盘都不产生候选。
- V0.1 不要求成交量确认，不加入 ATR、容差和自适应窗口。

## 实现

- 新增版本化 JSON fixture，共 8 个案例。
- 使用 FakeCryptoProvider 生成稳定时间窗口和 Provider identity。
- 使用 fixture OHLCV 重建 MarketBar，并通过完整契约校验生成 MarketSnapshot。
- 独立 expectation 固定 candidate_type、direction、reason_code 和参考结构值。
- 测试直接根据事实核对预期，不调用尚未存在的 PreFilter。

## 代码规范复核

- Python 命名、导入、行长和 docstring 符合项目 Python 规范。
- fixture `is_closed` 使用严格布尔校验，拒绝字符串真值转换。
- 测试使用包内相对导入，兼容定向运行和 unittest discovery。

## 验证

- Golden Case 定向测试：4 个通过。
- 完整 unittest：45 个通过，原基线 41 个全部保留。
- `compileall`：通过。
- context check：通过。

## 当时遗留事项（历史快照）

REQ-0005 必须直接复用本次 fixture，将相同预期参数化到 CryptoPreFilter；规则变化必须
新增版本，不能静默改写 V0.1。
