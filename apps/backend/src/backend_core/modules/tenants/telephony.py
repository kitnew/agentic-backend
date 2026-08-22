import asyncio
import logging
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING
from uuid import UUID

from agentic_observability.domain import CoreMetrics, domain_span
from contracts import TenantConfigV4, TenantConfigV5, TenantTelephonyConfig
from opentelemetry.trace import Tracer
from sqlalchemy.exc import IntegrityError

from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ConfigRevisionVersionConflictError,
    TelephonyPhoneConflictError,
    TenantNotFoundError,
)
from backend_core.modules.tenants.models import TelephonyProvisioningStatus
from backend_core.modules.tenants.repository import (
    TelephonyRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    CreateDraftRequest,
    PlatformTelephonyResponse,
    TelephonyReadiness,
    TenantTelephonyResponse,
    TenantTelephonyUpdate,
    UpdateDraftRequest,
)
from backend_core.modules.tenants.service import ConfigUseCases
from backend_core.platform.database import Database
from backend_core.platform.livekit import LiveKitAdapter

if TYPE_CHECKING:
    from backend_core.bootstrap.settings import Settings

logger = logging.getLogger(__name__)


class TenantTelephonyService:
    def __init__(
        self,
        tenants: TenantRepository,
        telephony: TelephonyRepository,
        configs: ConfigUseCases,
    ) -> None:
        self._tenants = tenants
        self._telephony = telephony
        self._configs = configs

    async def show(self, tenant_id: UUID) -> TenantTelephonyResponse:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        revisions = await self._configs.list_config_revisions(tenant_id)
        draft = next((item for item in revisions if item.status.value == "draft"), None)
        active = next(
            (item for item in revisions if item.id == tenant.active_config_revision_id),
            None,
        )
        actual = await self._telephony.get(tenant_id)
        actual_phone = actual.phone_number if actual else None
        desired = self._desired(draft or active, actual_phone)
        published = self._desired(active, None)
        projection_matches_published = (
            actual is not None
            and actual.config_revision_id == (active.id if active else None)
            and actual.phone_number == published.phone_number
            and actual.handoff_destinations
            == published.handoff.model_dump(mode="json")["destinations"]
        )
        platform = await self._telephony.platform()
        platform_ready = platform.provisioning_status is TelephonyProvisioningStatus.READY
        ready = projection_matches_published and platform_ready
        infrastructure = (
            "ready" if platform_ready else platform.provisioning_status.value
        )
        call_status = infrastructure if ready and published.phone_number else "pending"
        return TenantTelephonyResponse(
            tenant_id=tenant_id,
            desired=desired,
            draft_revision_id=draft.id if draft else None,
            draft_version=draft.version if draft else None,
            published_revision_id=active.id if active else None,
            provisioning_status=(
                actual.provisioning_status.value if actual else "pending"
            ),
            last_error=actual.last_error if actual else None,
            last_reconciled_at=actual.last_reconciled_at if actual else None,
            readiness=TelephonyReadiness(
                phone_number="ready" if ready and published.phone_number else "pending",
                incoming_calls=call_status,
                outgoing_calls=call_status,
                human_handoff=(
                    call_status if published.handoff.destinations else "pending"
                ),
            ),
        )

    async def save(
        self,
        tenant_id: UUID,
        data: TenantTelephonyUpdate,
        expected_version: int | None,
    ) -> TenantTelephonyResponse:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        revisions = await self._configs.list_config_revisions(tenant_id)
        draft = next((item for item in revisions if item.status.value == "draft"), None)
        source = draft or next(
            (item for item in revisions if item.id == tenant.active_config_revision_id),
            None,
        )
        if source is None:
            raise ActiveConfigNotFoundError
        if data.phone_number:
            owner = await self._telephony.phone_owner(data.phone_number)
            if owner is not None and owner != tenant_id:
                raise TelephonyPhoneConflictError
        config = dict(source.config)
        config.pop("handoff", None)
        config["schema_version"] = 5
        config["telephony"] = data.model_dump(mode="json")
        if draft is None:
            await self._configs.create_config_draft(
                tenant_id, CreateDraftRequest(schema_version=5, config=config)
            )
        else:
            if expected_version is None:
                raise ConfigRevisionVersionConflictError
            await self._configs.update_config_draft(
                tenant_id,
                draft.id,
                UpdateDraftRequest(schema_version=5, config=config),
                expected_version,
            )
        return await self.show(tenant_id)

    @staticmethod
    def _desired(revision, fallback_phone: str | None) -> TenantTelephonyConfig:
        if revision is None:
            return TenantTelephonyConfig()
        if revision.schema_version == 5:
            return TenantConfigV5.model_validate(revision.config).telephony
        if revision.schema_version == 4:
            legacy = TenantConfigV4.model_validate(revision.config)
            return TenantTelephonyConfig(
                phone_number=fallback_phone, handoff=legacy.handoff
            )
        return TenantTelephonyConfig(phone_number=fallback_phone)


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
        address = self._settings.sip_provider_address
        if not address:
            state.provisioning_status = TelephonyProvisioningStatus.DEGRADED
            state.last_error = "SIP provider connection is not configured"
            for tenant in await self._telephony.list():
                tenant.provisioning_status = TelephonyProvisioningStatus.DEGRADED
                tenant.last_error = "Platform SIP provider connection is not configured"
            await self._telephony.flush()
            if self._metrics is not None:
                self._metrics.telephony_reconciliation(
                    "degraded", monotonic() - started
                )
            return await self.show()
        numbers = sorted(
            item.phone_number
            for item in await self._telephony.active_published()
            if item.phone_number is not None
        )
        try:
            with domain_span(self._tracer, "telephony.reconcile"):
                inbound, outbound, dispatch = await self._livekit.reconcile_shared_sip(
                    numbers=numbers,
                    provider_address=address,
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
            state.inbound_trunk_id = inbound
            state.outbound_trunk_id = outbound
            state.dispatch_rule_id = dispatch
            state.provisioning_status = TelephonyProvisioningStatus.READY
            state.last_reconciled_at = datetime.now(UTC)
            for tenant in await self._telephony.list():
                tenant.provisioning_status = (
                    TelephonyProvisioningStatus.READY
                    if tenant.phone_number
                    else TelephonyProvisioningStatus.PENDING
                )
                tenant.last_error = None
                tenant.last_reconciled_at = state.last_reconciled_at
            await self._telephony.flush()
            if self._metrics is not None:
                self._metrics.telephony_reconciliation("ready", monotonic() - started)
        except IntegrityError as error:
            raise TelephonyPhoneConflictError from error
        except Exception as error:  # noqa: BLE001 - provider failures become persisted state
            state.provisioning_status = TelephonyProvisioningStatus.ERROR
            state.last_error = f"LiveKit reconciliation failed ({type(error).__name__})"
            for tenant in await self._telephony.list():
                tenant.provisioning_status = TelephonyProvisioningStatus.ERROR
                tenant.last_error = "Platform telephony is unavailable"
            await self._telephony.flush()
            if self._metrics is not None:
                self._metrics.telephony_reconciliation("error", monotonic() - started)
        return await self.show()


class PlatformTelephonyReconciler:
    """Poll the durable pending intent after publish commits."""

    def __init__(self, database: Database, livekit: LiveKitAdapter, settings: Settings,
                 tracer: Tracer | None = None, metrics: CoreMetrics | None = None) -> None:
        self._database = database
        self._livekit = livekit
        self._settings = settings
        self._tracer = tracer
        self._metrics = metrics

    async def run(self, interval_seconds: float) -> None:
        while True:
            try:
                async with self._database.transaction() as session:
                    repository = TelephonyRepository(session)
                    state = await repository.platform()
                    if state.provisioning_status is TelephonyProvisioningStatus.PENDING:
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
