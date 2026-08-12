import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "scripts" / "ops.sh"
COMPOSE = ROOT / "infrastructure" / "compose"


def fake_docker(tmp_path: Path) -> dict[str, str]:
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case " $* " in
  *" config --services "*)
    printf '%s\\n' backend postgres caddy livekit-egress
    ;;
  *" config --environment "*)
    printf 'BACKUP_DIR=%s\\n' "$FAKE_BACKUP_DIR"
    printf 'SECRETS_DIR=%s\\n' "$FAKE_SECRET_DIR"
    ;;
  *" config --format json "*)
    printf '{"secrets": {'
    first=true
    for name in postgres_password admin_api_token voice_agent_service_secret job_worker_service_secret livekit_api_secret elevenlabs_api_key azure_openai_api_key minio_root_password minio_egress_secret_key minio_worker_secret_key debug_chat_basic_auth_hash; do
      if [[ "$first" == true ]]; then first=false; else printf ','; fi
      printf '"%s":{"file":"%s/%s"}' "$name" "$FAKE_SECRET_DIR" "$name"
    done
    printf '}}\\n'
    ;;
  *" exec "*" pg_dump "*)
    printf 'fake-postgres-custom-archive'
    ;;
esac
"""
    )
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    return {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "DOCKER_LOG": str(log),
        "FAKE_BACKUP_DIR": str(tmp_path / "backups"),
        "FAKE_SECRET_DIR": str(tmp_path / "secrets"),
    }


def run_ops(
    tmp_path: Path,
    *arguments: str,
    input_text: str | None = None,
    prepare_secrets: bool = True,
) -> subprocess.CompletedProcess[str]:
    if prepare_secrets:
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir(exist_ok=True)
        for name in (
            "postgres_password",
            "admin_api_token",
            "voice_agent_service_secret",
            "job_worker_service_secret",
            "livekit_api_secret",
            "elevenlabs_api_key",
            "azure_openai_api_key",
            "minio_root_password",
            "minio_egress_secret_key",
            "minio_worker_secret_key",
            "debug_chat_basic_auth_hash",
        ):
            if not (secret_dir / name).exists():
                (secret_dir / name).write_text("test-secret")
    return subprocess.run(
        [str(OPS), *arguments],
        cwd=tmp_path,
        env=fake_docker(tmp_path),
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def docker_log(tmp_path: Path) -> str:
    path = tmp_path / "docker.log"
    return path.read_text() if path.exists() else ""


def test_config_resolves_staging_to_canonical_compose_arguments(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "staging", "config")

    assert result.returncode == 0, result.stderr
    expected = (
        f"compose --env-file {COMPOSE / '.env.staging'} "
        f"-f {COMPOSE / 'docker-compose.yml'} "
        f"-f {COMPOSE / 'docker-compose.deploy.yml'} config"
    )
    assert expected in docker_log(tmp_path)


def test_invalid_environment_never_invokes_docker(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "development", "status")

    assert result.returncode != 0
    assert "environment must be staging or production" in result.stderr
    assert docker_log(tmp_path) == ""


def test_logs_rejects_unknown_service(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "staging", "logs", "unknown")

    assert result.returncode != 0
    assert "unknown service" in result.stderr
    assert "logs --tail" not in docker_log(tmp_path)


def test_backup_uses_environment_directory_and_atomic_dump_name(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "staging", "backup")

    assert result.returncode == 0, result.stderr
    dump = Path(result.stdout.strip())
    assert dump.parent == tmp_path / "backups" / "staging" / "postgres"
    assert dump.suffix == ".dump"
    assert dump.read_bytes() == b"fake-postgres-custom-archive"
    assert not list(dump.parent.glob("*.tmp"))


def test_production_restore_requires_confirmation_unless_yes(tmp_path: Path) -> None:
    backup = tmp_path / "database.dump"
    backup.write_bytes(b"fake-postgres-custom-archive")

    rejected = run_ops(tmp_path, "production", "restore", str(backup), input_text="no\n")
    assert rejected.returncode != 0
    assert "production restore requires interactive confirmation or --yes" in rejected.stderr
    assert "pg_restore --clean" not in docker_log(tmp_path)

    accepted = run_ops(tmp_path, "production", "restore", str(backup), "--yes")
    assert accepted.returncode == 0, accepted.stderr
    commands = docker_log(tmp_path)
    backend_stop = commands.index("stop backend")
    writers_stop = commands.index("stop job-worker voice-agent")
    restore = commands.index("pg_restore --clean --if-exists --exit-on-error")
    migrate = commands.index("alembic -c apps/backend/alembic.ini upgrade head")
    restart = commands.index("up -d --wait --remove-orphans")
    assert backend_stop < writers_stop < restore < migrate < restart


def test_validate_rejects_empty_secret_without_printing_contents(tmp_path: Path) -> None:
    run_ops(tmp_path, "staging", "status")
    (tmp_path / "secrets" / "azure_openai_api_key").write_text("")
    result = run_ops(tmp_path, "staging", "validate", prepare_secrets=False)

    assert result.returncode != 0
    assert "empty" in result.stderr
    assert "test-secret" not in result.stderr


def test_validate_rejects_missing_secret_without_printing_contents(tmp_path: Path) -> None:
    run_ops(tmp_path, "staging", "status")
    (tmp_path / "secrets" / "livekit_api_secret").unlink()
    result = run_ops(tmp_path, "staging", "validate", prepare_secrets=False)

    assert result.returncode != 0
    assert "missing" in result.stderr
    assert "test-secret" not in result.stderr


def test_script_never_uses_derived_container_names_or_volume_deletion() -> None:
    source = OPS.read_text()

    assert "docker restart" not in source
    assert "down -v" not in source
    assert "container_name" not in source
