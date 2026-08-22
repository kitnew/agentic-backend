import asyncio
from datetime import datetime
from types import SimpleNamespace

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
        self.tenant = SimpleNamespace(
            phone_number="+421551234567",
            provisioning_status=TelephonyProvisioningStatus.PENDING,
            last_error=None,
            last_reconciled_at=None,
        )
        self.active = [self.tenant]

    async def platform(self, *, for_update: bool = False):
        return self.state

    async def list(self):
        return [self.tenant]

    async def active_published(self):
        return self.active

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
    service = PlatformTelephonyService(repository, livekit, settings)  # type: ignore[arg-type]

    failed = await service.reconcile()
    assert failed.overall == "error"
    assert "private provider detail" not in (failed.last_error or "")
    assert repository.tenant.provisioning_status is TelephonyProvisioningStatus.ERROR

    livekit.failure = None
    ready = await service.reconcile()
    assert ready.overall == "ready"
    assert ready.diagnostics == {
        "inbound_trunk_id": "ST_inbound",
        "outbound_trunk_id": "ST_outbound",
        "dispatch_rule_id": "SDR_shared",
    }
    assert repository.tenant.provisioning_status is TelephonyProvisioningStatus.READY
    assert isinstance(repository.tenant.last_reconciled_at, datetime)

    await service.reconcile()
    assert livekit.calls[-1]["inbound_trunk_id"] == "ST_inbound"
    assert livekit.calls[-1]["outbound_trunk_id"] == "ST_outbound"
    assert livekit.calls[-1]["dispatch_rule_id"] == "SDR_shared"

    repository.tenant.phone_number = "+421551234568"
    await service.reconcile()
    assert livekit.calls[-1]["numbers"] == ["+421551234568"]
    repository.active.clear()
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
            return SimpleNamespace(provisioning_status=TelephonyProvisioningStatus.PENDING)

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
        PlatformTelephonyReconciler(Database(), object(), object()).run(0)  # type: ignore[arg-type]
    )
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == 1
