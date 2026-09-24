import importlib.metadata
import platform
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def manifest(
    kind: str,
    provider: str,
    model: str | None,
    deployment: str | None,
    region: str | None,
    runs: int,
    warmups: int,
    parameters: dict,
) -> dict:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip()

    versions = {}
    for name in (
        "openai",
        "httpx",
        "websockets",
        "livekit-agents",
        "livekit-plugins-elevenlabs",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {
        "benchmark_type": kind,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": git("rev-parse", "HEAD"),
        "dirty_worktree": bool(git("status", "--porcelain")),
        "python_version": platform.python_version(),
        "operating_system": platform.platform(),
        "hostname": socket.gethostname(),
        "provider": provider,
        "model": model,
        "deployment": deployment,
        "configured_region": region,
        "measured_runs": runs,
        "warmup_runs": warmups,
        "parameters": parameters,
        "sdk_versions": versions,
    }
