from collections.abc import Mapping, Sequence
from typing import Any


class TenantNotFoundError(Exception):
    pass


class TenantSlugConflictError(Exception):
    pass


class ConfigRevisionError(Exception):
    pass


class ConfigRevisionNotFoundError(ConfigRevisionError):
    pass


class ActiveDraftExistsError(ConfigRevisionError):
    pass


class ConfigRevisionImmutableError(ConfigRevisionError):
    pass


class InvalidTenantConfigError(ConfigRevisionError):
    def __init__(self, errors: Sequence[Mapping[str, Any]]) -> None:
        self.errors = [dict(error) for error in errors]


class ActiveConfigNotFoundError(ConfigRevisionError):
    pass
