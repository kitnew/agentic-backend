import pytest
from backend_core.runtime.finalization.router import (
    MAX_RECORDING_BYTES,
    MAX_REPRESENTATION_BYTES,
    body,
)
from fastapi import HTTPException


class Request:
    async def stream(self):
        yield b"x" * (MAX_RECORDING_BYTES + 1)


@pytest.mark.asyncio
async def test_recording_larger_than_32_mib_is_rejected() -> None:
    with pytest.raises(HTTPException) as raised:
        await body(Request(), MAX_RECORDING_BYTES)  # type: ignore[arg-type]

    assert raised.value.status_code == 413


def test_base64_representation_limit_is_derived_from_recording_limit() -> None:
    assert MAX_RECORDING_BYTES == 32 * 1024 * 1024
    assert MAX_REPRESENTATION_BYTES == (MAX_RECORDING_BYTES + 2) // 3 * 4
