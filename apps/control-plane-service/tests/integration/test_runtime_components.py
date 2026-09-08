import pytest
from control_plane.application.components import ComponentService
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    TenantScope,
)
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.runtime_components import register_runtime_components
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.models import (
    ConfigurationComponentRevision,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_slice10_tenant_runtime_components_remain_independent(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    registry = ComponentDefinitionRegistry()
    register_runtime_components(registry)
    components = ComponentService(
        registry, SqlAlchemyComponentRepository(database.sessions)
    )
    architecture = ComponentAddress(
        ComponentKind("runtime.architecture.policy"), TenantScope("tenant-runtime")
    )
    speech = ComponentAddress(
        ComponentKind("runtime.speech.overrides"), TenantScope("tenant-runtime")
    )
    try:
        architecture_draft = await components.save_draft(
            architecture, {"architectures": ["realtime", "cascade"]}, None, None, "test"
        )
        architecture_first = await components.publish_draft(
            architecture, architecture_draft.version, "test"
        )
        speech_draft = await components.save_draft(
            speech,
            {
                "language": "sk",
                "stt": {"keyterms": ["Penzión Grand"]},
                "voices": {"cascade": None, "realtime": "marin"},
            },
            None,
            None,
            "test",
        )
        speech_first = await components.publish_draft(
            speech, speech_draft.version, "test"
        )
        architecture_draft = await components.save_draft(
            architecture,
            {"architectures": ["cascade"]},
            None,
            architecture_first.revision_id,
            "test",
        )
        await components.publish_draft(architecture, architecture_draft.version, "test")
        restored = await components.rollback(
            architecture, architecture_first.revision_number, "test"
        )
        assert restored.value.architectures == ["realtime", "cascade"]
        assert (
            await components.get_active(speech)
        ).revision_id == speech_first.revision_id

        async with database.sessions() as session:
            revisions = await session.scalar(
                select(func.count()).select_from(ConfigurationComponentRevision)
            )
        with pytest.raises(InvalidComponentValue):
            await components.save_draft(
                ComponentAddress(
                    ComponentKind("runtime.architecture.policy"),
                    TenantScope("invalid-runtime"),
                ),
                {"architectures": []},
                None,
                None,
                "test",
            )
        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(ConfigurationComponentRevision)
                )
                == revisions
            )
    finally:
        await database.close()
