from backend_core.modules.tenants.knowledge import (
    knowledge_content_hash,
    knowledge_content_matches,
    render_knowledge_context,
)


def test_knowledge_content_policy_and_runtime_rendering() -> None:
    assert knowledge_content_hash("facts") == (
        "0694aacb66d62e742a92e8d5f1e82bd9d2a8ca1be88744201fbe63d0f5007502"
    )
    assert knowledge_content_matches("facts\n", "facts")
    assert not knowledge_content_matches("facts\n\n", "facts")
    assert render_knowledge_context([("knowledge", "legacy text\n")]) == (
        "legacy text\n"
    )
    assert render_knowledge_context([("knowledge", "General"), ("rooms", "Rooms")]) == (
        "# Knowledge source: knowledge.md\n\nGeneral\n\n"
        "# Knowledge source: rooms.md\n\nRooms"
    )
