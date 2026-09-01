from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agentctl.commands.errors import CommandError


class StateStore:
    def __init__(self, root: Path, api_url: str) -> None:
        self.root = root
        self.path = root / ".agentctl" / "state.json"
        self.lock_path = root / ".agentctl" / "lock"
        self.api_url = api_url.rstrip("/")

    def read(self) -> dict:
        if not self.path.exists():
            return {"format_version": 1, "target": {"api_url": self.api_url}, "resources": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CommandError(f"invalid workspace state: {self.path}", 2) from error
        target = value.get("target", {})
        if target.get("api_url") != self.api_url:
            raise CommandError("workspace_target_mismatch: workspace is bound to another Backend target", 2)
        return value

    def write(self, value: dict) -> None:
        directory = self.path.parent
        directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(".state.json.agentctl.tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with temporary.open("rb") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise CommandError("workspace is locked by another agentctl process", 2) from error
        try:
            os.write(descriptor, str(os.getpid()).encode())
            yield
        finally:
            os.close(descriptor)
            self.lock_path.unlink(missing_ok=True)
