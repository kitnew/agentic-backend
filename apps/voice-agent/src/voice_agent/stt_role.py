from enum import StrEnum


class StandaloneSTTRole(StrEnum):
    PRIMARY = "primary"
    SIDECAR = "sidecar"


def role_for_architecture(architecture: str) -> StandaloneSTTRole:
    if architecture == "cascade":
        return StandaloneSTTRole.PRIMARY
    if architecture in ("realtime", "half-cascade"):
        return StandaloneSTTRole.SIDECAR
    raise ValueError(f"unsupported voice architecture: {architecture}")
