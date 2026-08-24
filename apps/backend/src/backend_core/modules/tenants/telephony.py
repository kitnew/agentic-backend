import asyncio
import logging
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING

from agentic_observability.domain import CoreMetrics, domain_span
from opentelemetry.trace import Tracer

from backend_core.modules.tenants.models import TelephonyProvisioningStatus
from backend_core.modules.tenants.release_repository import (
    TenantComponent,
    TenantReleaseRepository,
)
from backend_core.modules.tenants.repository import TelephonyRepository
from backend_core.modules.tenants.schemas import (
    PlatformTelephonyResponse,
    TelephonyClaimStatus,
    TelephonyDidState,
    TelephonyProvisioningStatusResponse,
    TenantTelephonyStatus,
)
from backend_core.platform.database import Database
from backend_core.platform.livekit import LiveKitAdapter

if TYPE_CHECKING:
    from backend_core.bootstrap.settings import Settings

logger = logging.getLogger(__name__)


class TenantTelephonyStatusService:
    def __init__(
        self, telephony: TelephonyRepository, releases: TenantReleaseRepository
    ) -> None:
        self._telephony = telephony
        self._releases = releases

    async def show(self, tenant_id) -> TenantTelephonyStatus:
        draft = await self._releases.draft(TenantComponent.TELEPHONY, tenant_id)
        release = await self._releases.active_release(tenant_id)
        published_revision = (
            None
            if release is None
            else await self._releases.revision(
                TenantComponent.TELEPHONY, tenant_id, release.telephony_revision_id
            )
        )
        draft_phone = None if draft is None else draft.payload.get("phone_number")
        published_phone = (
            None
            if published_revision is None
            else published_revision.payload.get("phone_number")
        )
        current_draft_phone = draft_phone if draft is not None else published_phone
        if draft is None and published_revision is None:
            publication = "empty"
        elif draft is None or draft_phone == published_phone:
            publication = "published"
        else:
            publication = "unpublished"
        claim = await self._releases.phone_claim_for_tenant(tenant_id)
        provisioning = await self._telephony.provisioning_for(tenant_id)
        provisioning_state = (
            "absent"
            if provisioning is None and published_phone is None
            else "pending"
            if provisioning is None
            else provisioning.status
        )
        return TenantTelephonyStatus(
            tenant_id=tenant_id,
            draft=None
            if current_draft_phone is None
            else TelephonyDidState(phone_number=current_draft_phone),
            published=(
                None
                if published_revision is None
                else TelephonyDidState(phone_number=published_phone)
            ),
            publication=publication,
            claim=TelephonyClaimStatus(
                state="absent" if claim is None else "active",
                phone_number=None if claim is None else claim.normalized_phone_number,
            ),
            provisioning=TelephonyProvisioningStatusResponse(
                state=provisioning_state,
                last_error=None if provisioning is None else provisioning.last_error,
                last_reconciled_at=(
                    None if provisioning is None else provisioning.last_reconciled_at
                ),
            ),
        )


class PlatformTelephonyService:
    def __init__(
        self,
        telephony: TelephonyRepository,
        livekit: LiveKitAdapter,
        settings: Settings,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
    ) -> None:
        self._telephony = telephony
        self._livekit = livekit
        self._settings = settings
        self._tracer = tracer
        self._metrics = metrics

    async def show(self) -> PlatformTelephonyResponse:
        state = await self._telephony.platform()
        configured = bool(self._settings.sip_provider_address)
        return PlatformTelephonyResponse(
            provider="connected" if configured else "configuration_required",
            inbound="ready" if state.inbound_trunk_id else "pending",
            outbound="ready" if state.outbound_trunk_id else "pending",
            dispatch="ready" if state.dispatch_rule_id else "pending",
            overall=state.provisioning_status.value,
            last_error=state.last_error,
            last_reconciled_at=state.last_reconciled_at,
            diagnostics={
                "inbound_trunk_id": state.inbound_trunk_id,
                "outbound_trunk_id": state.outbound_trunk_id,
                "dispatch_rule_id": state.dispatch_rule_id,
            },
        )

    async def reconcile(self) -> PlatformTelephonyResponse:
        started = monotonic()
        state = await self._telephony.platform(for_update=True)
        state.provisioning_status = TelephonyProvisioningStatus.PENDING
        state.last_error = None
        provisionings = await self._telephony.provisioning()
        if not self._settings.sip_provider_address:
            return await self._set_failure(
                state,
                provisionings,
                TelephonyProvisioningStatus.DEGRADED,
                "SIP provider connection is not configured",
                started,
            )
        numbers = sorted(
            claim.normalized_phone_number
            for claim in await self._telephony.active_phone_claims()
        )
        try:
            with domain_span(self._tracer, "telephony.reconcile"):
                inbound, outbound, dispatch = await self._livekit.reconcile_shared_sip(
                    numbers=numbers,
                    provider_address=self._settings.sip_provider_address,
                    provider_username=(
                        self._settings.sip_provider_username.get_secret_value()
                        if self._settings.sip_provider_username
                        else None
                    ),
                    provider_password=(
                        self._settings.sip_provider_password.get_secret_value()
                        if self._settings.sip_provider_password
                        else None
                    ),
                    agent_name=self._settings.livekit_agent_name,
                    inbound_trunk_id=state.inbound_trunk_id,
                    outbound_trunk_id=state.outbound_trunk_id,
                    dispatch_rule_id=state.dispatch_rule_id,
                )
            state.inbound_trunk_id, state.outbound_trunk_id, state.dispatch_rule_id = (
                inbound,
                outbound,
                dispatch,
            )
            state.provisioning_status = TelephonyProvisioningStatus.READY
            state.last_reconciled_at = datetime.now(UTC)
            for item in provisionings:
                item.applied_revision_id = item.desired_revision_id
                item.status = "ready"
                item.last_error = None
                item.last_reconciled_at = state.last_reconciled_at
            await self._telephony.flush()
            if self._metrics is not None:
                self._metrics.telephony_reconciliation("ready", monotonic() - started)
        except Exception as error:  # noqa: BLE001 - provider error becomes durable state
            return await self._set_failure(
                state,
                provisionings,
                TelephonyProvisioningStatus.ERROR,
                f"LiveKit reconciliation failed ({type(error).__name__})",
                started,
            )
        return await self.show()

    async def _set_failure(
        self, state, items, status, message: str, started: float
    ) -> PlatformTelephonyResponse:
        state.provisioning_status = status
        state.last_error = message
        for item in items:
            item.status = status.value
            item.last_error = message
        await self._telephony.flush()
        if self._metrics is not None:
            self._metrics.telephony_reconciliation(status.value, monotonic() - started)
        return await self.show()


class PlatformTelephonyReconciler:
    def __init__(
        self,
        database: Database,
        livekit: LiveKitAdapter,
        settings: Settings,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
    ) -> None:
        self._database, self._livekit, self._settings = database, livekit, settings
        self._tracer, self._metrics = tracer, metrics

    async def run(self, interval_seconds: float) -> None:
        while True:
            try:
                async with self._database.transaction() as session:
                    repository = TelephonyRepository(session)
                    platform = await repository.platform()
                    provisionings = await repository.provisioning()
                    if (
                        platform.provisioning_status
                        is TelephonyProvisioningStatus.PENDING
                        or any(
                            item.status == TelephonyProvisioningStatus.PENDING.value
                            for item in provisionings
                        )
                    ):
                        await PlatformTelephonyService(
                            repository,
                            self._livekit,
                            self._settings,
                            self._tracer,
                            self._metrics,
                        ).reconcile()
            except Exception:
                logger.exception("Automatic platform telephony reconciliation failed")
            await asyncio.sleep(interval_seconds)
