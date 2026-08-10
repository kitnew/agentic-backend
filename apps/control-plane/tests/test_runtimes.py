from pathlib import Path

import pytest
from control_plane.commands import runtimes
from control_plane.commands.prompts import PromptCommandError


def test_runtime_yaml_is_safe_single_mapping_and_supports_empty_override() -> None:
    assert runtimes.parse_runtime_yaml("{}\n", platform=False) == {}
    for document, message in (
        ("- voice-a\n", "root must be a mapping"),
        ("{}\n---\n{}\n", "exactly one document"),
        ("!!python/object/apply:os.system ['unsafe']", "invalid TenantRuntime YAML"),
        ("tts:\n  voice_id: .nan\n", "must be finite"),
        ("created: 2026-08-10\n", "JSON-compatible"),
    ):
        with pytest.raises(PromptCommandError, match=message):
            runtimes.parse_runtime_yaml(document, platform=False)


def test_runtime_paths_and_serialization_are_canonical(tmp_path: Path) -> None:
    assert runtimes.platform_runtime_path(tmp_path) == tmp_path / "platform/runtime.yaml"
    assert runtimes.tenant_runtime_path(tmp_path, "debug-hotel") == (
        tmp_path / "tenants/debug-hotel/runtime.yaml"
    )
    rendered = runtimes.serialize_runtime_yaml({"tts": {"voice_id": "hlas-á"}})
    assert rendered == "tts:\n  voice_id: hlas-á\n"
