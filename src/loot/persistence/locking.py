"""PostgreSQL 事务 advisory lock 的稳定键生成工具。"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from sqlalchemy.engine import Connection


def advisory_lock_key(identity: str) -> int:
    """把业务身份稳定映射为 PostgreSQL signed bigint lock key。"""

    raw_key = int.from_bytes(
        hashlib.sha256(identity.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=False,
    )
    return raw_key if raw_key < 2 ** 63 else raw_key - 2 ** 64


def acquire_advisory_locks(connection: Connection, *identities: str) -> None:
    """按稳定顺序获取当前事务持有的业务身份锁，避免锁顺序死锁。"""

    for lock_key in sorted({advisory_lock_key(identity) for identity in identities}):
        connection.execute(
            sa.select(sa.func.pg_advisory_xact_lock(lock_key))
        ).scalar_one()
