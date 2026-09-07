import base64
from uuid import uuid4

from control_plane.application.credentials import CredentialService
from control_plane.domain.managed_resources import PlatformCredentialScope
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence.credential_transactions import (
    credential_command_scope,
)
from control_plane.infrastructure.persistence.database import Database


def credential_service(database: Database) -> CredentialService:
    cipher = CredentialCipher(base64.b64encode(b"0" * 32).decode())
    return CredentialService(credential_command_scope(database.sessions, cipher))


async def create_platform_credential(
    database: Database, name: str, secret: str = "secret", actor: str = "test"
):
    return await credential_service(database).create(
        PlatformCredentialScope(), name, secret, actor, str(uuid4())
    )
