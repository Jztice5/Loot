# 本地运行说明

## 当前状态

当前仓库已建立初始 Python 项目骨架和核心 contracts。`main.py` 仍是 PyCharm 示例脚本，正式 API、worker 和数据库尚未启动。

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
Ran 12 tests
OK
```

## 编译检查

```bash
py -3.12 -m compileall src tests
```
