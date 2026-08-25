import argparse
import asyncio
import os

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from backend_core.platform.database.metadata import Base
from backend_core.platform.database.model_registry import load_models


def registered_table_names() -> tuple[str, ...]:
    load_models()
    return tuple(sorted(Base.metadata.tables))


def _database_table_names(connection) -> set[str]:
    return set(inspect(connection).get_table_names(schema="public"))


async def ensure_schema(database_url: str, *, create: bool) -> set[str]:
    expected = set(registered_table_names())
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            if create:
                await connection.run_sync(Base.metadata.create_all)
            actual = await connection.run_sync(_database_table_names)
    finally:
        await engine.dispose()

    missing = expected - actual
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"database schema is missing tables: {names}")
    return actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap or check Backend SQLAlchemy schema")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the registered schema without creating tables",
    )
    args = parser.parse_args(argv)
    database_url = os.environ["DATABASE_URL"]
    action = "checked" if args.check else "bootstrapped"
    tables = asyncio.run(ensure_schema(database_url, create=not args.check))
    print(f"Database schema {action}: {len(registered_table_names())} registered tables ({len(tables)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
