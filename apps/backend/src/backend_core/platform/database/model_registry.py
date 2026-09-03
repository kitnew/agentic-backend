from backend_core.modules.calls.models import CallSession
from backend_core.modules.conversations.models import Conversation, ConversationMessage
from backend_core.modules.tenants.models import PlatformTelephony, Tenant
from backend_core.modules.tenants.telephony_models import TenantTelephonyProvisioning
from backend_core.runtime.capabilities.models import CapabilityInvocation, OutboxMessage
from backend_core.runtime.finalization.models import (
    ArtifactRepresentation,
    CallFinalization,
    CallRecording,
    PostCallActionExecution,
)


def load_models() -> tuple[object, ...]:
    """Return every model class that contributes tables to Base.metadata."""
    return (
        CallSession,
        Conversation,
        ConversationMessage,
        PlatformTelephony,
        Tenant,
        TenantTelephonyProvisioning,
        CapabilityInvocation,
        OutboxMessage,
        ArtifactRepresentation,
        CallFinalization,
        CallRecording,
        PostCallActionExecution,
    )
