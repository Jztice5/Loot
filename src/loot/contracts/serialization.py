"""跨进程契约的 canonical JSON 与内容指纹工具。

业务描述:
    把 Pydantic 契约或 JSON 兼容值序列化为稳定 JSON，并计算 SHA-256 内容指纹。

业务场景:
    PostgreSQL 不可变事实写入、Inbox 去重、Ticket 消费幂等和跨进程冲突检测。

业务原因:
    Python 对象表示、字典插入顺序和数据库 JSONB 展示顺序都不能作为幂等依据，所有
    生产者和消费者必须共享同一套 canonical 规则。

调用链:
    Contract/Repository/Workflow -> canonical_json -> payload_fingerprint

业务规则:
    使用 Pydantic JSON mode 归一化 UUID、datetime、Decimal 和 Enum；JSON 键排序且不
    保留无意义空白；指纹固定为 64 位小写 SHA-256 十六进制字符串。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, TypeAdapter

_JSON_VALUE_ADAPTER = TypeAdapter(
    dict[str, Any] | list[Any] | tuple[Any, ...] | str | int | float | bool | None
)


def json_compatible(value: Any) -> Any:
    """把契约或普通值转换为可写入 JSONB 的 JSON 兼容结构。"""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return _JSON_VALUE_ADAPTER.dump_python(value, mode="json")


def canonical_json(value: Any) -> str:
    """生成键排序、无多余空白且只包含 ASCII 转义的稳定 JSON。"""

    return json.dumps(
        json_compatible(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def payload_fingerprint(value: Any) -> str:
    """计算锁定完整 canonical payload 的 SHA-256 指纹。"""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
