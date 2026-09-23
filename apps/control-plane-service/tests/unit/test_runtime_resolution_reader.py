from datetime import UTC, datetime
from uuid import uuid4

from control_plane.domain.components import ComponentAddress, ComponentKind, SystemScope
from control_plane.domain.live_components import LiveComponentState
from control_plane.infrastructure.persistence.runtime_resolution import (
    SqlAlchemyRuntimeResolutionReader,
)


def test_realtime_input_transcription_deployment_is_loaded_separately() -> None:
    model, input_transcription, standalone_stt = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    realtime: LiveComponentState[dict[str, object]] = LiveComponentState(
        ComponentAddress(ComponentKind("RealtimeDefaults"), SystemScope()),
        {
            "deployment_ref": str(model),
            "input_transcription": {"deployment_ref": str(input_transcription)},
        },
        1,
        1,
        now,
        "test",
    )
    stt: LiveComponentState[dict[str, object]] = LiveComponentState(
        ComponentAddress(ComponentKind("STTDefaults"), SystemScope()),
        {"deployment_ref": str(standalone_stt)},
        1,
        1,
        now,
        "test",
    )

    assert SqlAlchemyRuntimeResolutionReader._deployment_ids((realtime, stt)) == {
        model,
        input_transcription,
        standalone_stt,
    }
