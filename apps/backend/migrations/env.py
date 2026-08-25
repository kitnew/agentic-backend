from asyncio import run
from logging.config import fileConfig
from os import environ

from alembic import context
from backend_core.platform.database.metadata import Base
from backend_core.platform.database.model_registry import load_models
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

load_models()

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def url() -> str:
    return config.get_main_option("sqlalchemy.url") or environ["DATABASE_URL"]


def configure(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(configure)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run(online())
