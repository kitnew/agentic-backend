from uuid import uuid4

import pytest
from backend_core.modules.calls.models import CallSessionStatus
from backend_core.modules.calls.router import observe_call
from contracts import VoiceCallObservation


class Service:
    def __init__(self) -> None:
        self.observed: list[str] = []
        self.call = type(
            "Call",
            (),
            {
                "id": uuid4(),
                "status": CallSessionStatus.CREATED,
                "started_at": None,
                "connected_at": None,
                "ended_at": None,
                "failure_reason": None,
            },
        )()

    async def mark_started(self, call_id):
        self.observed.append("started")
        self.call.status = CallSessionStatus.STARTED
        return self.call

    async def mark_connected(self, call_id):
        self.observed.append("connected")
        self.call.status = CallSessionStatus.CONNECTED
        return self.call

    async def relinquish_agent(self, call_id, conversation_status):
        self.observed.append(f"relinquished:{conversation_status.value}")
        return self.call


@pytest.mark.asyncio
async def test_runtime_observation_routes_to_authoritative_call_service() -> None:
    service = Service()

    response = await observe_call(
        service.call.id,
        VoiceCallObservation(observation_type="session_started"),
        service,  # type: ignore[arg-type]
    )

    assert service.observed == ["started"]
    assert response.status.value == "started"


@pytest.mark.asyncio
async def test_agent_relinquish_does_not_end_the_call() -> None:
    service = Service()
    service.call.status = CallSessionStatus.CONNECTED

    response = await observe_call(
        service.call.id,
        VoiceCallObservation(observation_type="agent_relinquished"),
        service,  # type: ignore[arg-type]
    )

    assert service.observed == ["relinquished:complete"]
    assert response.status.value == "connected"
