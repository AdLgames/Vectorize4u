"""Bring a development database up to head.

`create_all` at startup creates missing *tables*; it never adds a column to
a table that already exists. So a dev database made before a migration
silently keeps the old shape, and the first insert that uses the new column
fails at runtime — which is exactly how this script came to exist.

Databases created by `create_all` have no `alembic_version` row, so they are
stamped at the initial revision before upgrading.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402

INITIAL = "36a7dbf29ddb"


def main() -> int:
    cfg = settings()
    if cfg.is_production:
        print("refusing to run the dev helper against production", file=sys.stderr)
        return 1

    inspector = inspect(engine())
    tables = set(inspector.get_table_names())

    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))

    if tables and "alembic_version" not in tables:
        # Made by create_all before migrations were tracked here.
        print(f"stamping an untracked database at {INITIAL}")
        command.stamp(config, INITIAL)

    command.upgrade(config, "head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
