import pytest
from control_plane.domain.managed_resource_errors import InvalidManagedResource
from control_plane.domain.managed_resources import DeploymentKind
from control_plane.domain.registries import ProviderKindRegistry


def test_soniox_connection_uses_late_bound_credential_only() -> None:
    registry = ProviderKindRegistry()

    assert registry.validate_connection("soniox", {"region": "eu"}) == {"region": "eu"}
    with pytest.raises(InvalidManagedResource):
        registry.validate_connection("soniox", {"api_key": "plaintext"})


def test_soniox_connection_only_accepts_known_regions() -> None:
    registry = ProviderKindRegistry()

    assert registry.validate_connection("soniox", {}) == {"region": "global"}
    with pytest.raises(InvalidManagedResource):
        registry.validate_connection("soniox", {"region": "custom-url"})


def test_soniox_only_accepts_rt_v5_stt_with_bounded_endpoint_options() -> None:
    registry = ProviderKindRegistry()

    assert registry.validate_deployment("soniox", DeploymentKind.STT, {}) == {
        "model": "stt-rt-v5",
        "max_endpoint_delay_ms": 2000,
        "endpoint_sensitivity": None,
        "endpoint_latency_adjustment_level": None,
    }
    assert (
        registry.validate_deployment(
            "soniox",
            DeploymentKind.STT,
            {"model": "stt-rt-v5", "max_endpoint_delay_ms": 500},
        )["max_endpoint_delay_ms"]
        == 500
    )
    with pytest.raises(InvalidManagedResource):
        registry.validate_deployment(
            "soniox", DeploymentKind.STT, {"model": "stt-rt-v4"}
        )
    with pytest.raises(InvalidManagedResource):
        registry.validate_deployment(
            "soniox", DeploymentKind.TTS, {"model": "stt-rt-v5"}
        )
