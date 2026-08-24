import base64
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from backend_core.modules.integrations.crypto import (
    IntegrationSecretCipher,
    derive_observability_key,
)
from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationConnectionStatus,
    IntegrationCredential,
    IntegrationCredentialStatus,
    IntegrationProvider,
)
from backend_core.modules.integrations.schemas import (
    ConfigureIntegrationConnectionRequest,
    IntegrationCredentialWrite,
    UpdateIntegrationConnectionRequest,
)
from backend_core.modules.integrations.service import (
    CapabilityIntegrationResolver,
    IntegrationConnectionError,
    IntegrationConnectionService,
)
from contracts import GoogleSheetsAppendValuesPlan, HttpRequestPlanV1

KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
SECRET = {
    "service_account": {
        "client_email": "test@example.test",
        "private_key": "key",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def test_observability_key_is_domain_separated_from_master_key() -> None:
    derived = derive_observability_key(KEY)
    assert derived != base64.b64decode(KEY)
    assert derived == derive_observability_key(KEY)


class Tenants:
    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id

    async def get(self, tenant_id: UUID) -> object | None:
        return object() if tenant_id == self.tenant_id else None


class Connections:
    def __init__(self, connection: IntegrationConnection) -> None:
        self.connection = connection
        self.credentials: list[IntegrationCredential] = []

    async def get(self, tenant_id: UUID, connection_id: UUID):
        if (
            tenant_id == self.connection.tenant_id
            and connection_id == self.connection.id
        ):
            return self.connection
        return None

    async def get_by_key(self, tenant_id: UUID, key: str):
        if tenant_id == self.connection.tenant_id and key == self.connection.key:
            return self.connection
        return None

    async def get_by_key_for_update(self, tenant_id: UUID, key: str):
        return await self.get_by_key(tenant_id, key)

    async def get_for_update(self, tenant_id: UUID, connection_id: UUID):
        return await self.get(tenant_id, connection_id)

    async def active_credential(
        self, integration_id: UUID, *, for_update: bool = False
    ):
        assert integration_id == self.connection.id
        return next(
            (
                credential
                for credential in self.credentials
                if credential.status is IntegrationCredentialStatus.ACTIVE
            ),
            None,
        )

    async def add_credential(self, credential: IntegrationCredential) -> None:
        self.credentials.append(credential)

    async def flush(self) -> None:
        pass

    async def refresh(self, connection: IntegrationConnection) -> None:
        assert connection is self.connection


def connection() -> IntegrationConnection:
    return IntegrationConnection(
        id=uuid4(),
        tenant_id=uuid4(),
        key="sheets",
        provider=IntegrationProvider.GOOGLE_SHEETS,
        config={},
        revision=1,
        status=IntegrationConnectionStatus.DISABLED,
    )


def http_connection(
    *, authentication: str = "none", enabled: bool = True
) -> IntegrationConnection:
    auth = {"type": "none"}
    if authentication == "api_key_header":
        auth = {"type": authentication, "header_name": "X-API-Key"}
    return IntegrationConnection(
        id=uuid4(),
        tenant_id=uuid4(),
        key="check-availability",
        provider=IntegrationProvider.HTTP,
        config={
            "endpoint": "https://api.example.com/v1",
            "headers": {},
            "authentication": auth,
            "security": {"additional_allowed_hosts": []},
        },
        revision=1,
        enabled=enabled,
    )


def service(
    value: IntegrationConnection,
) -> tuple[IntegrationConnectionService, Connections]:
    connections = Connections(value)
    return (
        IntegrationConnectionService(
            Tenants(value.tenant_id), connections, IntegrationSecretCipher(KEY)
        ),
        connections,
    )


@pytest.mark.asyncio
async def test_credentials_rotate_atomically_and_revocation_stops_resolution() -> None:
    value = connection()
    integrations, connections = service(value)

    first = await integrations.set_secret(
        value.tenant_id, value.id, SECRET, rotate=False
    )
    assert first.credential is not None and first.credential.version == 1
    assert b"test@example.test" not in first.credential.ciphertext
    await integrations.update(
        value.tenant_id,
        value.id,
        UpdateIntegrationConnectionRequest(status=IntegrationConnectionStatus.ACTIVE),
    )
    assert (await integrations.test(value.tenant_id, value.id)).credential is not None
    second = await integrations.set_secret(
        value.tenant_id,
        value.id,
        {
            **SECRET,
            "service_account": {
                **SECRET["service_account"],
                "client_email": "rotated@example.test",
            },
        },
        rotate=True,
    )
    assert second.credential is not None and second.credential.version == 2
    assert connections.credentials[0].status is IntegrationCredentialStatus.RETIRED
    assert (
        integrations.material(value, second.credential).secret["service_account"][
            "client_email"
        ]
        == "rotated@example.test"
    )

    await integrations.revoke_secret(value.tenant_id, value.id)
    with pytest.raises(IntegrationConnectionError, match="credential_missing"):
        integrations.material(value, second.credential)
    with pytest.raises(IntegrationConnectionError, match="connection_not_found"):
        await integrations.set_secret(uuid4(), value.id, SECRET, rotate=False)


def test_http_without_auth_materializes_without_credential() -> None:
    value = http_connection()
    integrations, _ = service(value)

    readiness = integrations._readiness(value, None)
    material = integrations.material(value, None)

    assert readiness.credentials == "not_required"
    assert readiness.ready is True
    assert readiness.usable is True
    assert material.secret is None
    assert material.credential_version is None
    assert material.authentication_header is None


@pytest.mark.asyncio
async def test_get_by_id_is_tenant_scoped() -> None:
    value = http_connection()
    integrations, _ = service(value)

    view = await integrations.get_by_id(value.tenant_id, value.id)
    assert view.connection is value

    with pytest.raises(IntegrationConnectionError, match="integration_not_found"):
        await integrations.get_by_id(uuid4(), value.id)


def test_http_authentication_requires_credential() -> None:
    value = http_connection(authentication="api_key_header")
    integrations, _ = service(value)

    readiness = integrations._readiness(value, None)
    assert readiness.credentials == "missing"
    assert readiness.usable is False
    with pytest.raises(IntegrationConnectionError, match="credential_missing"):
        integrations.material(value, None)


@pytest.mark.asyncio
async def test_api_key_configuration_can_save_before_credential() -> None:
    value = http_connection(authentication="none", enabled=True)
    integrations, _ = service(value)
    request = ConfigureIntegrationConnectionRequest(
        configuration={
            **value.configuration,
            "authentication": {"type": "api_key_header", "header_name": "X-API-Key"},
        }
    )

    plan = await integrations.plan(value.tenant_id, value.key, request)
    assert plan.valid is True
    assert plan.would_be_ready is False
    assert plan.issues == []

    with_credential = request.model_copy(
        update={"credential": IntegrationCredentialWrite(api_key="secret")}
    )
    supplied_plan = await integrations.plan(value.tenant_id, value.key, with_credential)
    assert supplied_plan.valid is True
    assert supplied_plan.would_be_ready is True
    assert supplied_plan.issues == []

    saved = await integrations.configure(value.tenant_id, value.key, request, 1)
    assert saved.connection.configuration["authentication"] == {
        "type": "api_key_header",
        "header_name": "X-API-Key",
    }
    assert saved.readiness.credentials == "missing"
    with pytest.raises(IntegrationConnectionError, match="credential_missing"):
        integrations.material(value, None)


@pytest.mark.asyncio
async def test_rotate_creates_first_http_credential_and_enable_remains_fail_closed() -> None:
    value = http_connection(authentication="api_key_header", enabled=False)
    integrations, _ = service(value)

    with pytest.raises(IntegrationConnectionError, match="integration_not_ready"):
        await integrations.set_enabled(value.tenant_id, value.key, True)

    credential = await integrations.rotate(value.tenant_id, value.key, "secret")
    assert credential.credential is not None
    assert credential.credential.version == 1
    assert credential.readiness.credentials == "configured"

    enabled = await integrations.set_enabled(value.tenant_id, value.key, True)
    assert enabled.connection.enabled is True
    assert enabled.readiness.usable is True


@pytest.mark.asyncio
async def test_http_authentication_materializes_with_valid_credential() -> None:
    value = http_connection(authentication="api_key_header")
    integrations, _ = service(value)

    credential = (
        await integrations.set_secret(
            value.tenant_id, value.id, {"api_key": "secret"}, rotate=False
        )
    ).credential
    assert credential is not None

    material = integrations.material(value, credential)

    assert material.secret == {"api_key": "secret"}
    assert material.credential_version == credential.version
    assert material.authentication_header == "X-API-Key"


def test_disabled_http_connection_does_not_materialize() -> None:
    value = http_connection(enabled=False)
    integrations, _ = service(value)

    with pytest.raises(IntegrationConnectionError, match="integration_disabled"):
        integrations.material(value, None)


@pytest.mark.asyncio
async def test_capability_material_requires_the_pinned_invocation_job_and_tenant() -> (
    None
):
    value = connection()
    integrations, connections = service(value)
    credential = (
        await integrations.set_secret(value.tenant_id, value.id, SECRET, rotate=False)
    ).credential
    assert credential is not None
    await integrations.update(
        value.tenant_id,
        value.id,
        UpdateIntegrationConnectionRequest(status=IntegrationConnectionStatus.ACTIVE),
    )
    job_id = uuid4()
    invocation_id = uuid4()
    plan = GoogleSheetsAppendValuesPlan(
        plan_type="google_sheets.append_values.v1",
        integration_id=value.id,
        spreadsheet_id="sheet",
        sheet_name="Sheet1",
        append_range="A:D",
        value_input_option="RAW",
        rows=[["id"]],
        idempotency={
            "operation_id": uuid4(),
            "lookup_range": "A:A",
            "operation_id_column_index": 0,
        },
    )

    class Invocations:
        async def get(self, requested: UUID):
            if requested != invocation_id:
                return None
            return SimpleNamespace(
                job_id=job_id,
                tenant_id=value.tenant_id,
                execution_plan=plan.model_dump(mode="json"),
            )

    resolver = CapabilityIntegrationResolver(Invocations(), connections, integrations)
    material = await resolver.resolve(invocation_id, job_id)
    assert material.integration_id == value.id
    with pytest.raises(IntegrationConnectionError, match="capability_not_found"):
        await resolver.resolve(invocation_id, uuid4())


@pytest.mark.asyncio
async def test_capability_material_resolves_http_without_authentication() -> None:
    value = http_connection()
    integrations, connections = service(value)
    invocation_id = uuid4()
    job_id = uuid4()
    plan = HttpRequestPlanV1(
        integration_id=value.id,
        operation_id=uuid4(),
        capability={"semantic_key": "reservation.check_availability", "semantic_version": 1},
        method="POST",
        request={"codec": "none"},
        response={"codec": "none"},
        timeout_seconds=5,
    )

    class Invocations:
        async def get(self, requested: UUID):
            if requested != invocation_id:
                return None
            return SimpleNamespace(
                job_id=job_id,
                tenant_id=value.tenant_id,
                execution_plan=plan.model_dump(mode="json"),
            )

    material = await CapabilityIntegrationResolver(
        Invocations(), connections, integrations
    ).resolve(invocation_id, job_id)

    assert material.provider == "http"
    assert material.endpoint == "https://api.example.com/v1"
    assert material.secret is None
    assert material.credential_version is None
