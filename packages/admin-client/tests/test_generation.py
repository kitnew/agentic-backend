from pathlib import Path

from scripts.generate_admin_client import drift, snapshot


def test_generated_client_is_current() -> None:
    assert drift() == []


def test_snapshot_detects_intentional_drift(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    changed = tmp_path / "changed"
    expected.mkdir()
    changed.mkdir()
    (expected / "client.py").write_text("generated\n")
    (changed / "client.py").write_text("changed\n")

    assert snapshot(expected) != snapshot(changed)
