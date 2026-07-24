"""PostgreSQL engine construction for Loot persistence adapters.

业务描述:
    从显式 DSN 创建 SQLAlchemy Engine，供 Repository、migration 验证和集成测试使用。

业务原因:
    数据库密码必须留在环境变量或 DBX，不允许由业务模块拼接、记录或提交。

调用链:
    environment/secret store -> create_postgres_engine -> Repository/Workflow
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine


def create_postgres_engine(database_url: str) -> Engine:
    """创建开启连接健康检查的 PostgreSQL Engine。

    Args:
        database_url: SQLAlchemy psycopg DSN；调用方负责从安全环境读取。

    Returns:
        配置为 future mode、连接前探活的 SQLAlchemy Engine。
    """

    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("database_url must use postgresql+psycopg")
    return create_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
    )
