from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure" / "compose"
BASE = (COMPOSE / "docker-compose.yml").read_text()
DEPLOY = (COMPOSE / "docker-compose.deploy.yml").read_text()


def test_private_persistent_minio_and_idempotent_bucket_init() -> None:
    assert "minio/minio:RELEASE.2025-09-07T16-13-09Z" in DEPLOY
    assert "minio/mc:RELEASE.2025-08-13T08-35-41Z" in DEPLOY
    assert "minio-data:/data" in DEPLOY
    assert "minio-data:" in DEPLOY
    assert "mc mb --ignore-existing local/call-recordings" in DEPLOY
    assert "mc anonymous set none local/call-recordings" in DEPLOY
    assert "9000:9000" not in DEPLOY
    assert "9001:9001" not in DEPLOY


def test_egress_is_pinned_private_and_uses_shared_redis_and_global_s3() -> None:
    assert "livekit/egress:v1.13.0" in DEPLOY
    assert 'address: "${LIVEKIT_EGRESS_REDIS_ADDRESS:-redis:6379}"' in DEPLOY
    assert "storage:" in DEPLOY
    assert "force_path_style: true" in DEPLOY
    assert "enable_chrome_sandbox: true" in DEPLOY
    assert "seccomp=../livekit/egress/chrome-sandboxing-seccomp-profile.json" in DEPLOY
    assert "LIVEKIT_EGRESS_HEALTH_PORT:-8080}:8080" not in DEPLOY


def test_credentials_follow_service_responsibilities() -> None:
    backend = BASE[BASE.index("  backend:") : BASE.index("  voice-agent:")]
    voice = BASE[BASE.index("  voice-agent:") : BASE.index("  job-worker:")]
    worker = DEPLOY[DEPLOY.index("  job-worker:") : DEPLOY.index("  admin-web:")]
    assert "MINIO_" not in backend
    assert "MINIO_" not in voice
    assert "MINIO_WORKER_ACCESS_KEY" in worker
    assert "MINIO_EGRESS_ACCESS_KEY" not in worker
