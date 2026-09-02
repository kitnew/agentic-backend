import asyncio
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.tenants import telephony as telephony_module
from backend_core.modules.tenants.models import TelephonyProvisioningStatus
from backend_core.modules.tenants.telephony import (
    PlatformTelephonyReconciler,
    PlatformTelephonyService,
)


class Repository:
    def __init__(self) -> None:
        self.state = SimpleNamespace(
            inbound_trunk_id=None,
            outbound_trunk_id=None,
            dispatch_rule_id=None,
            provisioning_status=TelephonyProvisioningStatus.PENDING,
            last_error=None,
            last_reconciled_at=None,
        )
        assignment_id = uuid4()
        self.provisioning_state = SimpleNamespace(
            phone_assignment_id=assignment_id,
            desired_generation=1,
            applied_generation=None,
            status="pending",
            last_error=None,
            last_reconciled_at=None,
        )
        self.assignment = SimpleNamespace(
            assignment_id=assignment_id,
            tenant_id=uuid4(),
            phone_number="+421551234567",
            generation=1,
        )

    async def platform(self, *, for_update: bool = False):
        return self.state

    async def provisioning(self):
        return [self.provisioning_state]

    async def provisioning_for(self, tenant_id, assignment_id):
        return self.provisioning_state if assignment_id == self.assignment.assignment_id else None

    async def add(self, value):
        self.provisioning_state = value

    async def flush(self) -> None:
        pass


class LiveKit:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.failure: Exception | None = RuntimeError("private provider detail")

    async def reconcile_shared_sip(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return "ST_inbound", "ST_outbound", "SDR_shared"


class ControlPlane:
    def __init__(self, repository):
        self.repository = repository

    async def list_enabled_phone_assignments(self):
        return [self.repository.assignment] if self.repository.assignment else []


@pytest.mark.asyncio
async def test_reconciliation_persists_failure_then_retries_with_stored_ids() -> None:
    repository = Repository()
    livekit = LiveKit()
    settings = SimpleNamespace(
        sip_provider_address="sip.provider.example",
        sip_provider_username=None,
        sip_provider_password=None,
        livekit_agent_name="voice-agent",
    )
    service = PlatformTelephonyService(repository, livekit, settings, ControlPlane(repository))  # type: ignore[arg-type]

    failed = await service.reconcile()
    assert failed.overall == "error"
    assert "private provider detail" not in (failed.last_error or "")
    assert repository.provisioning_state.status == "error"

    livekit.failure = None
    ready = await service.reconcile()
    assert ready.overall == "ready"
    assert ready.diagnostics == {
        "inbound_trunk_id": "ST_inbound",
        "outbound_trunk_id": "ST_outbound",
        "dispatch_rule_id": "SDR_shared",
    }
    assert repository.provisioning_state.status == "ready"
    assert isinstance(repository.provisioning_state.last_reconciled_at, datetime)

    await service.reconcile()
    assert livekit.calls[-1]["inbound_trunk_id"] == "ST_inbound"
    assert livekit.calls[-1]["outbound_trunk_id"] == "ST_outbound"
    assert livekit.calls[-1]["dispatch_rule_id"] == "SDR_shared"

    repository.assignment.phone_number = "+421551234568"
    await service.reconcile()
    assert livekit.calls[-1]["numbers"] == ["+421551234568"]
    repository.assignment = None
    await service.reconcile()
    assert livekit.calls[-1]["numbers"] == []


@pytest.mark.asyncio
async def test_pending_publish_is_reconciled_automatically_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Transaction:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return False

    class Database:
        def transaction(self):
            return Transaction()

    calls = 0

    class Repository:
        async def platform(self):
            return SimpleNamespace(provisioning_status=TelephonyProvisioningStatus.READY)

        async def provisioning(self):
            return [SimpleNamespace(status=TelephonyProvisioningStatus.PENDING.value)]

    class Service:
        def __init__(self, *_args, **_kwargs):
            pass

        async def reconcile(self):
            nonlocal calls
            calls += 1
            raise asyncio.CancelledError

    monkeypatch.setattr(telephony_module, "TelephonyRepository", lambda _session: Repository())
    monkeypatch.setattr(telephony_module, "PlatformTelephonyService", Service)
    task = asyncio.create_task(
        PlatformTelephonyReconciler(Database(), object(), object(), object()).run(0)  # type: ignore[arg-type]
    )
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == 1
