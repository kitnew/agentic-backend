from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.platform.database.connection import Database


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Open one transaction for a request handler and commit before its response."""
    database: Database = request.app.state.database
    async with database.transaction() as session:
        yield session


DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_session, scope="function"),
]
