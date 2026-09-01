class ComponentError(Exception):
    code = "component_error"


class UnknownComponentKind(ComponentError):
    code = "unknown_component_kind"


class ScopeNotAllowed(ComponentError):
    code = "scope_not_allowed"


class InvalidComponentValue(ComponentError):
    code = "invalid_component_value"


class UnsupportedSchemaVersion(ComponentError):
    code = "unsupported_schema_version"


class ComponentNotFound(ComponentError):
    code = "component_not_found"


class DraftNotFound(ComponentError):
    code = "draft_not_found"


class RevisionNotFound(ComponentError):
    code = "revision_not_found"


class DraftVersionConflict(ComponentError):
    code = "draft_version_conflict"


class ActiveRevisionConflict(ComponentError):
    code = "active_revision_conflict"


class UnpublishedDraftConflict(ComponentError):
    code = "unpublished_draft_blocks_rollback"
