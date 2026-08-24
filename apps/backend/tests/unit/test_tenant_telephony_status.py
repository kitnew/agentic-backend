from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.tenants.telephony import TenantTelephonyStatusService

TENANT_ID = uuid4()


class FakeTelephony:
    def __init__(self, provisioning=None):
        self._provisioning = provisioning

    async def provisioning_for(self, tenant_id):
        return self._provisioning


class FakeReleases:
    def __init__(self, draft=None, revision=None, claim=None):
        self._draft = draft
        self._revision = revision
        self._claim = claim

    async def draft(self, component, tenant_id):
        return self._draft

    async def active_release(self, tenant_id):
        return (
            None
            if self._revision is None
            else SimpleNamespace(telephony_revision_id=uuid4())
        )

    async def revision(self, component, tenant_id, revision_id):
        return self._revision

    async def phone_claim_for_tenant(self, tenant_id):
        return self._claim


@pytest.mark.asyncio
async def test_empty_status_is_normal() -> None:
    result = await TenantTelephonyStatusService(FakeTelephony(), FakeReleases()).show(
        TENANT_ID
    )
    assert result.publication == "empty"
    assert result.draft is None and result.published is None
    assert result.claim.state == "absent"
    assert result.provisioning.state == "absent"


@pytest.mark.asyncio
async def test_unpublished_draft_keeps_published_claim() -> None:
    draft = SimpleNamespace(payload={"phone_number": "+421900000002"})
    revision = SimpleNamespace(payload={"phone_number": "+421900000001"})
    claim = SimpleNamespace(normalized_phone_number="+421900000001")
    result = await TenantTelephonyStatusService(
        FakeTelephony(
            SimpleNamespace(status="ready", last_error=None, last_reconciled_at=None)
        ),
        FakeReleases(draft, revision, claim),
    ).show(TENANT_ID)
    assert result.publication == "unpublished"
    assert result.claim.phone_number == "+421900000001"
    assert result.provisioning.state == "ready"


@pytest.mark.asyncio
async def test_published_revision_is_current_draft_when_draft_was_consumed() -> None:
    revision = SimpleNamespace(payload={"phone_number": "+421900000001"})
    result = await TenantTelephonyStatusService(
        FakeTelephony(), FakeReleases(draft=None, revision=revision)
    ).show(TENANT_ID)
    assert result.draft is not None
    assert result.draft.phone_number == "+421900000001"
    assert result.published is not None
    assert result.published.phone_number == "+421900000001"
    assert result.publication == "published"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "degraded", "error"])
async def test_persisted_provisioning_state_and_error_are_exposed(state: str) -> None:
    revision = SimpleNamespace(payload={"phone_number": "+421900000001"})
    provisioning = SimpleNamespace(
        status=state, last_error="safe persisted reason", last_reconciled_at=None
    )
    result = await TenantTelephonyStatusService(
        FakeTelephony(provisioning),
        FakeReleases(
            draft=SimpleNamespace(payload={"phone_number": "+421900000002"}),
            revision=revision,
        ),
    ).show(TENANT_ID)
    assert result.publication == "unpublished"
    assert result.provisioning.state == state
    assert result.provisioning.last_error == "safe persisted reason"
