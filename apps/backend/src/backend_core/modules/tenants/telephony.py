import asyncio
import logging
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING

from agentic_observability.domain import CoreMetrics, domain_span
from opentelemetry.trace import Tracer

from backend_core.modules.tenants.models import TelephonyProvisioningStatus
from backend_core.modules.tenants.repository import TelephonyRepository
from backend_core.modules.tenants.schemas import (
    PlatformTelephonyResponse,
    TelephonyClaimStatus,
    TelephonyProvisioningStatusResponse,
    TenantTelephonyStatus,
)
from backend_core.modules.tenants.telephony_models import TenantTelephonyProvisioning
from backend_core.platform.control_plane import ControlPlaneClient
from backend_core.platform.database import Database
from backend_core.platform.livekit import LiveKitAdapter

if TYPE_CHECKING:
    from backend_core.bootstrap.settings import Settings

logger = logging.getLogger(__name__)


class TenantTelephonyStatusService:
    def __init__(
        self, telephony: TelephonyRepository
    ) -> None:
        self._telephony = telephony

    async def show(self, tenant_id) -> TenantTelephonyStatus:
        provisioning = await self._telephony.provisioning_for(tenant_id)
        provisioning_state = (
            "absent"
            if provisioning is None
            else "pending"
            if provisioning is None
            else provisioning.status
        )
        return TenantTelephonyStatus(
            tenant_id=tenant_id,
            draft=None,
            published=None,
            publication="empty",
            claim=TelephonyClaimStatus(state="absent", phone_number=None),
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
        control_plane: ControlPlaneClient,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
    ) -> None:
        self._telephony = telephony
        self._livekit = livekit
        self._settings = settings
        self._control_plane = control_plane
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
        try:
            assignments = await self._control_plane.list_enabled_phone_assignments()
            numbers = sorted(item.phone_number for item in assignments)
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
            for assignment in assignments:
                item = await self._telephony.provisioning_for(assignment.tenant_id, assignment.assignment_id)
                if item is None:
                    item = next((value for value in provisionings if value.tenant_id == assignment.tenant_id), None)
                if item is None:
                    item = TenantTelephonyProvisioning(
                        tenant_id=assignment.tenant_id,
                        phone_assignment_id=assignment.assignment_id,
                        desired_generation=assignment.generation,
                    )
                    await self._telephony.add(item)
                item.phone_assignment_id = assignment.assignment_id
                item.desired_generation = assignment.generation
                item.applied_generation = assignment.generation
                item.status = "ready"
                item.last_error = None
                item.last_reconciled_at = state.last_reconciled_at
            for item in provisionings:
                if not any(item.phone_assignment_id == a.assignment_id for a in assignments):
                    item.status = "degraded"
                    item.last_error = "assignment is no longer enabled"
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
        control_plane: ControlPlaneClient,
        tracer: Tracer | None = None,
        metrics: CoreMetrics | None = None,
    ) -> None:
        self._database, self._livekit, self._settings = database, livekit, settings
        self._tracer, self._metrics, self._control_plane = tracer, metrics, control_plane

    async def run(self, interval_seconds: float) -> None:
        while True:
            try:
                async with self._database.transaction() as session:
                    repository = TelephonyRepository(session)
                    await repository.platform()
                    await PlatformTelephonyService(
                        repository,
                        self._livekit,
                        self._settings,
                        self._control_plane,
                        self._tracer,
                        self._metrics,
                    ).reconcile()
            except Exception:
                logger.exception("Automatic platform telephony reconciliation failed")
            await asyncio.sleep(interval_seconds)
