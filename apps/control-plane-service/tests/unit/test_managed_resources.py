import base64
from uuid import uuid4

import pytest
from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import (
    CredentialRef,
    DeploymentKind,
    ModelDeploymentRef,
)
from control_plane.domain.providers import default_provider_registry
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.interfaces.http.app import (
    ModelDeploymentUpdate,
    ProviderConnectionUpdate,
)
from pydantic import ValidationError


def test_typed_refs_are_distinct_and_immutable() -> None:
    value = uuid4()
    credential = CredentialRef(value)
    deployment = ModelDeploymentRef(value)

    assert credential != deployment
    with pytest.raises(AttributeError):
        credential.value = uuid4()  # type: ignore[misc]


def test_resource_identity_fields_cannot_be_supplied_to_updates() -> None:
    connection = {
        "credential_ref": str(uuid4()),
        "connection_config": {},
        "expected_generation": 1,
        "actor": "test",
    }
    deployment = {
        "connection_ref": str(uuid4()),
        "deployment_config": {},
        "expected_generation": 1,
        "actor": "test",
    }
    with pytest.raises(ValidationError, match="provider_kind"):
        ProviderConnectionUpdate.model_validate({**connection, "provider_kind": "x"})
    with pytest.raises(ValidationError, match="deployment_kind"):
        ModelDeploymentUpdate.model_validate({**deployment, "deployment_kind": "stt"})


def test_provider_registry_validates_current_provider_shapes() -> None:
    registry = default_provider_registry()
    azure = registry.resolve("azure_openai")
    elevenlabs = registry.resolve("elevenlabs")

    assert azure.validate_connection(
        {"endpoint": "https://example.openai.azure.com"}
    ) == {"endpoint": "https://example.openai.azure.com/"}
    assert (
        azure.validate_deployment(
            DeploymentKind.LLM,
            {
                "deployment_name": "chat-prod",
                "model": "gpt-5.6-terra",
                "api_version": "2025-01-01-preview",
            },
        )["deployment_name"]
        == "chat-prod"
    )
    assert azure.validate_deployment(
        DeploymentKind.REALTIME, {"deployment_name": "realtime-prod"}
    ) == {"deployment_name": "realtime-prod"}
    assert azure.validate_deployment(
        DeploymentKind.STT, {"deployment_name": "whisper-prod"}
    ) == {"deployment_name": "whisper-prod"}
    assert elevenlabs.validate_connection({}) == {}
    assert elevenlabs.validate_deployment(
        DeploymentKind.STT, {"model_id": "scribe_v2_realtime"}
    ) == {"model_id": "scribe_v2_realtime"}
    assert elevenlabs.validate_deployment(
        DeploymentKind.TTS, {"model_id": "eleven_flash_v2_5"}
    ) == {"model_id": "eleven_flash_v2_5"}

    with pytest.raises(InvalidManagedResource, match="unknown provider"):
        registry.resolve("unknown")
    with pytest.raises(InvalidManagedResource):
        elevenlabs.validate_connection({"endpoint": "https://example.com"})
    with pytest.raises(InvalidManagedResource, match="does not support llm"):
        elevenlabs.validate_deployment(DeploymentKind.LLM, {"model_id": "x"})


def test_credential_cipher_uses_authenticated_resource_bound_encryption() -> None:
    cipher = CredentialCipher(base64.b64encode(b"0" * 32).decode())
    credential_id = uuid4()
    nonce, ciphertext = cipher.encrypt(credential_id, 1, "secret-value")

    assert b"secret-value" not in ciphertext
    assert (
        cipher.decrypt(
            credential_id, 1, nonce, ciphertext, cipher.key_id, cipher.ALGORITHM
        )
        == "secret-value"
    )
    with pytest.raises(ValueError, match="could not be decrypted"):
        cipher.decrypt(
            credential_id, 2, nonce, ciphertext, cipher.key_id, cipher.ALGORITHM
        )
    with pytest.raises(ValueError, match="envelope is not supported"):
        cipher.decrypt(
            credential_id, 1, nonce, ciphertext, "retired-key", cipher.ALGORITHM
        )
