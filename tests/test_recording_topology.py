from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure" / "compose"
BASE = (COMPOSE / "docker-compose.yml").read_text()


def test_private_persistent_minio_and_idempotent_bucket_init() -> None:
    assert "minio/minio:RELEASE.2025-09-07T16-13-09Z" in BASE
    assert "minio/mc:RELEASE.2025-08-13T08-35-41Z" in BASE
    assert "minio-data:/data" in BASE
    assert "minio-data:" in BASE
    assert "mc mb --ignore-existing local/call-recordings" in BASE
    assert "mc anonymous set none local/call-recordings" in BASE
    assert "9000:9000" not in BASE
    assert "9001:9001" not in BASE


def test_egress_is_pinned_private_and_uses_shared_redis_and_global_s3() -> None:
    assert "livekit/egress:v1.13.0" in BASE
    assert 'address: "${LIVEKIT_EGRESS_REDIS_ADDRESS:-redis:6379}"' in BASE
    assert "storage:" in BASE
    assert "force_path_style: true" in BASE
    assert "enable_chrome_sandbox: true" in BASE
    assert "seccomp=../livekit/egress/chrome-sandboxing-seccomp-profile.json" in BASE
    assert "LIVEKIT_EGRESS_HEALTH_PORT:-8080}:8080" not in BASE


def test_credentials_follow_service_responsibilities() -> None:
    backend = BASE[BASE.index("  backend:") : BASE.index("  voice-agent:")]
    voice = BASE[BASE.index("  voice-agent:") : BASE.index("  job-worker:")]
    worker = BASE[BASE.index("  job-worker:") :]
    assert "MINIO_" not in backend
    assert "MINIO_" not in voice
    assert "MINIO_WORKER_ACCESS_KEY" in worker
    assert "MINIO_EGRESS_ACCESS_KEY" not in worker
