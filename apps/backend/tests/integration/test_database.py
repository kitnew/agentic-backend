import pytest
from backend_core.platform.database import Database
from sqlalchemy import text


@pytest.mark.asyncio
async def test_migrations_and_transaction_round_trip(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.transaction() as session:
            await session.execute(
                text(
                    "CREATE TABLE persistence_probe "
                    "(id integer PRIMARY KEY, value text NOT NULL)"
                )
            )
            await session.execute(
                text("INSERT INTO persistence_probe VALUES (1, :value)"),
                {"value": "committed"},
            )

        with pytest.raises(RuntimeError):
            async with database.transaction() as session:
                await session.execute(
                    text("INSERT INTO persistence_probe VALUES (2, 'rolled back')")
                )
                raise RuntimeError("force rollback")

        async with database.transaction() as session:
            values = (
                (
                    await session.execute(
                        text("SELECT value FROM persistence_probe ORDER BY id")
                    )
                )
                .scalars()
                .all()
            )
            revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )

        assert values == ["committed"]
        assert revision == "20260804_0010"
    finally:
        await database.close()
