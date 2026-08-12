import pytest
from backend_core.runtime.finalization.router import (
    MAX_REPRESENTATION_BYTES,
    body,
)
from fastapi import HTTPException


class Request:
    async def stream(self):
        yield b"x" * (MAX_REPRESENTATION_BYTES + 1)


@pytest.mark.asyncio
async def test_postgres_representation_larger_than_limit_is_rejected() -> None:
    with pytest.raises(HTTPException) as raised:
        await body(Request(), MAX_REPRESENTATION_BYTES)  # type: ignore[arg-type]

    assert raised.value.status_code == 413
