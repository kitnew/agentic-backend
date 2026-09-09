from uuid import uuid4

import httpx
import pytest
from backend_core.modules.calls.errors import CallSessionConfigUnavailableError
from backend_core.modules.calls.service import CallSessionService


class ControlPlane:
    async def create_execution(self, *_args, **_kwargs):
        request = httpx.Request("POST", "http://control-plane/internal/v1/executions")
        response = httpx.Response(422, request=request)
        raise httpx.HTTPStatusError(
            "configuration rejected", request=request, response=response
        )


@pytest.mark.asyncio
async def test_execution_resolution_422_becomes_configuration_unavailable() -> None:
    service = CallSessionService(
        None,
        None,
        None,
        None,
        None,
        ControlPlane(),  # type: ignore[arg-type]
    )

    with pytest.raises(CallSessionConfigUnavailableError):
        await service._execution(uuid4(), "test-execution")
