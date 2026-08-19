import base64
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from backend_core.modules.integrations.crypto import IntegrationSecretCipher
from backend_core.modules.integrations.models import (
    IntegrationConnection,
    IntegrationConnectionStatus,
    IntegrationCredential,
    IntegrationCredentialStatus,
    IntegrationProvider,
)
from backend_core.modules.integrations.schemas import UpdateIntegrationConnectionRequest
from backend_core.modules.integrations.service import (
    CapabilityIntegrationResolver,
    IntegrationConnectionError,
    IntegrationConnectionService,
)
from contracts import GoogleSheetsAppendValuesPlan

KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
SECRET = {
    "service_account": {
        "client_email": "test@example.test",
        "private_key": "key",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


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
    with pytest.raises(IntegrationConnectionError, match="credential_not_configured"):
        integrations.material(value, second.credential)
    with pytest.raises(IntegrationConnectionError, match="connection_not_found"):
        await integrations.set_secret(uuid4(), value.id, SECRET, rotate=False)


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
