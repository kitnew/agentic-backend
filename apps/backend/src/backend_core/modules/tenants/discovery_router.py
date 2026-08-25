from contracts import (
    CANONICAL_FIELD_DESCRIPTIONS,
    CANONICAL_FIELDS,
    CapabilityDiscoveryResponse,
    CatalogDescriptor,
    PostCallArtifactDescriptor,
    PostCallDiscoveryResponse,
)
from fastapi import APIRouter, Depends

from backend_core.platform.auth import require_admin

router = APIRouter(
    prefix="/admin/v1/authoring/discovery",
    tags=["admin:authoring-discovery"],
    dependencies=[Depends(require_admin)],
)


def _domain_fields() -> list[CatalogDescriptor]:
    return [
        CatalogDescriptor(
            path=path,
            type=field_type,
            description=CANONICAL_FIELD_DESCRIPTIONS[path],
            category=path.split(".", 1)[0],
        )
        for path, field_type in CANONICAL_FIELDS.items()
    ]


def _capability_context() -> list[CatalogDescriptor]:
    return [
        item.model_copy(update={"path": f"business.{item.path}"})
        for item in _domain_fields()
    ] + [
        CatalogDescriptor(path=path, type=field_type, description=description, category="metadata")
        for path, field_type, description in [
            ("metadata.operation_id", "string", "Operation identifier"),
            ("metadata.invocation_id", "string", "Capability invocation identifier"),
            ("metadata.call_id", "string", "Call identifier"),
            ("metadata.tool_call_id", "string", "Tool call identifier"),
            ("metadata.caller_phone", "string", "Caller phone number"),
            ("business.custom.*", "json", "Capability-specific custom input fields"),
        ]
    ]


@router.get("/capabilities", response_model=CapabilityDiscoveryResponse)
async def capabilities() -> CapabilityDiscoveryResponse:
    return CapabilityDiscoveryResponse(
        semantics=[],
        domain_fields=_domain_fields(),
        mapping_context=_capability_context(),
    )


@router.get("/post-call", response_model=PostCallDiscoveryResponse)
async def post_call() -> PostCallDiscoveryResponse:
    return PostCallDiscoveryResponse(
        artifacts=[
            PostCallArtifactDescriptor(
                artifact="transcript",
                representations=["raw_json", "plain_text"],
                description="Conversation transcript",
            ),
            PostCallArtifactDescriptor(
                artifact="call_recording",
                representations=["original", "base64_text"],
                description="Call recording",
            ),
            PostCallArtifactDescriptor(
                artifact="call_summary",
                representations=["plain_text"],
                description="Generated call summary",
            ),
        ],
        mapping_context=[
            CatalogDescriptor(path="call.id", type="string", description="Call identifier", category="call"),
            CatalogDescriptor(path="call.conversation_id", type="string", description="Conversation identifier", category="call"),
            CatalogDescriptor(path="call.caller_number", type="string", description="Caller phone number", category="call"),
            CatalogDescriptor(path="call.started_at", type="string", description="Call start time", category="call"),
            CatalogDescriptor(path="call.ended_at", type="string", description="Call end time", category="call"),
            CatalogDescriptor(path="agent.id", type="string", description="Agent profile identifier", category="agent"),
            CatalogDescriptor(path="agent.name", type="string", description="Agent display name", category="agent"),
            CatalogDescriptor(path="inputs.*", type="json", description="Declared action inputs", category="inputs"),
        ],
    )
