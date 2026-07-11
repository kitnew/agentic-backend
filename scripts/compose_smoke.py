import subprocess
import sys
import urllib.request


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def health(port: int) -> None:
    with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=10) as response:
        assert response.status == 200


def main() -> None:
    run("docker", "compose", "up", "--build", "--detach", "--wait")
    try:
        health(8000)
        health(8001)
        run(sys.executable, "scripts/voice_ws_smoke.py")
        run("docker", "compose", "exec", "-T", "api", "python", "scripts/capability_compose_smoke.py")
        run("docker", "compose", "restart", "api")
        health(8001)
        run("docker", "compose", "restart", "agent-runtime")
        health(8000)
        run("docker", "compose", "ps", "--status", "running", "capability-worker")
    finally:
        run("docker", "compose", "down")


if __name__ == "__main__":
    main()
