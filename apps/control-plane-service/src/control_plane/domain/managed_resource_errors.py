from control_plane.domain.common.errors import DomainError


class ManagedResourceError(DomainError):
    code = "managed_resource_conflict"


class ManagedResourceNotFound(ManagedResourceError):
    code = "managed_resource_not_found"


class ManagedResourceConflict(ManagedResourceError):
    code = "managed_resource_conflict"


class InvalidManagedResource(ManagedResourceError):
    code = "invalid_managed_resource"
