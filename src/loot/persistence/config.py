"""Loot 本地数据库配置加载。

业务描述:
    为本地开发和集成测试读取数据库连接配置，优先使用进程环境变量，其次使用用户目录
    下的私有配置文件。

业务场景:
    PyCharm、PowerShell 或自动化测试需要连接 ``loot_test``，但不应把密码写入仓库。

业务原因:
    IDE 临时运行配置容易丢失，源码硬编码又会泄露凭据；用户级配置可以兼顾可重复运行
    和本地密钥隔离。

调用链:
    test/runtime -> load_local_setting -> environment | user config -> database engine

业务规则:
    环境变量优先；默认配置位于用户主目录之外的仓库路径；空值和格式错误不会被静默接受。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_LOCAL_CONFIG_PATH = Path.home() / ".loot" / "database.env"


def load_local_setting(
        name: str,
        *,
        config_path: Path | None = None,
) -> str | None:
    """读取环境变量或用户级本地配置中的非空值。

    调用链:
        validate name -> environment lookup -> user config parse -> return value

    Args:
        name: 需要读取的环境变量名称。
        config_path: 测试或特殊环境指定的配置路径；默认使用用户级 Loot 配置。

    Returns:
        已去除外围引号的配置值；未配置时返回 ``None``。
    """

    normalized_name = name.strip()
    if not normalized_name or "=" in normalized_name:
        raise ValueError("setting name must be a non-empty environment variable name")

    environment_value = os.environ.get(normalized_name)
    if environment_value is not None and environment_value.strip():
        return environment_value.strip()

    selected_path = config_path or DEFAULT_LOCAL_CONFIG_PATH
    if not selected_path.is_file():
        return None

    for raw_line in selected_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != normalized_name:
            continue
        normalized_value = value.strip()
        if (
                len(normalized_value) >= 2
                and normalized_value[0] == normalized_value[-1]
                and normalized_value[0] in {"'", '"'}
        ):
            normalized_value = normalized_value[1:-1]
        return normalized_value or None
    return None
