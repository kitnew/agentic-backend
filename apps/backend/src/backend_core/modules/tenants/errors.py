from collections.abc import Mapping, Sequence
from typing import Any


class TenantNotFoundError(Exception):
    pass


class TenantSlugConflictError(Exception):
    pass


class InboundRouteNotFoundError(Exception):
    pass


class InboundRouteDidConflictError(Exception):
    pass


class InboundRouteUnavailableError(Exception):
    pass


class PromptBundleRevisionError(Exception):
    pass


class PromptBundleRevisionNotFoundError(PromptBundleRevisionError):
    pass


class PromptBundleActiveDraftExistsError(PromptBundleRevisionError):
    pass


class PromptBundleRevisionImmutableError(PromptBundleRevisionError):
    pass


class PromptBundleRevisionVersionConflictError(PromptBundleRevisionError):
    pass


class PromptRevisionError(Exception):
    pass


class PromptRevisionNotFoundError(PromptRevisionError):
    pass


class PromptRevisionImmutableError(PromptRevisionError):
    pass


class PromptRevisionVersionConflictError(PromptRevisionError):
    pass


class PromptRevisionActiveDraftExistsError(PromptRevisionError):
    pass


class InvalidPromptSetError(PromptRevisionError):
    pass


class PromptSetResolutionError(PromptRevisionError):
    def __init__(self, path: str, code: str, message: str) -> None:
        self.path = path
        self.code = code
        self.message = message


class ConfigRevisionError(Exception):
    pass


class ConfigRevisionNotFoundError(ConfigRevisionError):
    pass


class ActiveDraftExistsError(ConfigRevisionError):
    pass


class ConfigRevisionImmutableError(ConfigRevisionError):
    pass


class ConfigRevisionVersionConflictError(ConfigRevisionError):
    pass


class InvalidTenantConfigError(ConfigRevisionError):
    def __init__(self, errors: Sequence[Mapping[str, Any]]) -> None:
        self.errors = [dict(error) for error in errors]


class ActiveConfigNotFoundError(ConfigRevisionError):
    pass
