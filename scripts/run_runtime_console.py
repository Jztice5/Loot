"""Start the local read-only Runtime Console."""

from __future__ import annotations

import argparse
from wsgiref.simple_server import make_server

from loot.observability import create_runtime_console_app
from loot.persistence.config import load_local_setting
from loot.persistence.database import create_postgres_engine


def parse_args() -> argparse.Namespace:
    """解析观察台本地监听参数，不接收数据库口令参数。"""

    parser = argparse.ArgumentParser(description="Start Loot's read-only Runtime Console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> int:
    """从用户级 loot_test 配置启动只读观察台。"""

    args = parse_args()
    database_url = load_local_setting("LOOT_TEST_DATABASE_URL")
    if not database_url:
        print("LOOT_TEST_DATABASE_URL is not configured")
        return 2

    engine = create_postgres_engine(database_url)
    application = create_runtime_console_app(engine)
    with make_server(args.host, args.port, application) as server:
        print(f"Loot Runtime Console: http://{args.host}:{args.port}")
        print("Read-only mode; press Ctrl+C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Runtime Console stopped")
        finally:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
