import argparse
import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, UniqueConstraint, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from backend_core.platform.database.metadata import Base
from backend_core.platform.database.model_registry import load_models


def registered_table_names() -> tuple[str, ...]:
    load_models()
    return tuple(sorted(Base.metadata.tables))


def _database_table_names(connection) -> set[str]:
    return set(inspect(connection).get_table_names(schema="public"))


def _baseline_metadata() -> MetaData:
    metadata = MetaData()
    phase3_tables = {
        "call_sessions",
        "capability_invocations",
        "capability_confirmations",
    }
    for table in Base.metadata.tables.values():
        clone = table.to_metadata(metadata)
        if table.name in phase3_tables:
            clone._columns.remove(clone.columns["execution_snapshot_id"])  # type: ignore[attr-defined]
    return metadata


def _schema_differences(connection, metadata: MetaData) -> list[object]:
    context = MigrationContext.configure(connection)
    return [
        difference
        for difference in compare_metadata(context, metadata)
        if not _ignorable_schema_difference(difference)
    ]


def _ignorable_schema_difference(difference: object) -> bool:
    if isinstance(difference, list):
        return bool(difference) and all(
            _ignorable_schema_difference(item) for item in difference
        )
    if not isinstance(difference, tuple) or not difference:
        return False
    if difference[0] == "remove_table":
        return True
    if difference[0] != "add_constraint" or len(difference) != 2:
        return False
    constraint = difference[1]
    # PostgreSQL omits a redundant UNIQUE that duplicates a composite PK from
    # reflected metadata even when the pre-Alembic ORM emitted it.
    if getattr(constraint, "name", None) == "uq_platform_release_profile":
        return True
    return (
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns}
        == {column.name for column in constraint.table.primary_key.columns}
    )


async def ensure_schema(database_url: str) -> set[str]:
    expected = set(registered_table_names())
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            actual = await connection.run_sync(_database_table_names)
    finally:
        await engine.dispose()

    missing = expected - actual
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"database schema is missing tables: {names}")
    return actual


async def baseline_needs_stamp(database_url: str) -> bool:
    """Return whether a complete matching legacy schema needs the baseline stamp."""
    expected = set(registered_table_names())
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            actual = await connection.run_sync(_database_table_names)
            if "alembic_version" in actual:
                print("Backend Alembic history already exists; applying migrations.")
                return False
            present = expected & actual
            if not present:
                print("Backend schema is empty; applying initial migration.")
                return False
            differences = await connection.run_sync(
                lambda sync_connection: _schema_differences(
                    sync_connection, _baseline_metadata()
                )
            )
    finally:
        await engine.dispose()

    if differences:
        raise RuntimeError(
            "existing Backend schema differs from 0001_initial_backend; "
            f"refusing to stamp: {differences!r}"
        )
    return True


def stamp_baseline(database_url: str) -> None:
    config = Config(str(Path(__file__).parents[4] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.stamp(config, "0001_initial_backend")
    print("Existing Backend schema matches 0001_initial_backend; stamped baseline.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or adopt the Backend Alembic baseline")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the registered Backend schema",
    )
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="stamp 0001 only when an existing Backend schema exactly matches",
    )
    args = parser.parse_args(argv)
    database_url = os.environ["DATABASE_URL"]
    if args.adopt:
        if asyncio.run(baseline_needs_stamp(database_url)):
            stamp_baseline(database_url)
        return 0
    if not args.check:
        parser.error("use Alembic to create schema; only --check or --adopt is supported")
    tables = asyncio.run(ensure_schema(database_url))
    print(f"Database schema checked: {len(registered_table_names())} registered tables ({len(tables)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
