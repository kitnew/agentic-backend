import argparse
import asyncio
import socket
import ssl
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.artifacts import append, create, finish
from common.config import load_env
from common.metadata import manifest


def measure(url: str) -> dict:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError("endpoint lacks host")
    port = parsed.port or (443 if parsed.scheme in ("https", "wss") else 80)
    start = time.perf_counter_ns()
    row = {
        "request_start_utc": datetime.now(UTC).isoformat(),
        "status": "ok",
        "target_host": host,
        "scheme": parsed.scheme,
    }
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        dns_end = time.perf_counter_ns()
        row["dns_ms"] = (dns_end - start) / 1e6
        address = addresses[0]
        with socket.socket(address[0], socket.SOCK_STREAM) as raw:
            raw.settimeout(10)
            raw.connect(address[4])
            connected = time.perf_counter_ns()
            row["tcp_ms"] = (connected - dns_end) / 1e6
            if parsed.scheme in ("https", "wss"):
                with ssl.create_default_context().wrap_socket(
                    raw, server_hostname=host
                ) as sock:
                    tls_end = time.perf_counter_ns()
                    row["tls_ms"] = (tls_end - connected) / 1e6
                    if parsed.scheme == "https":
                        sock.sendall(
                            f"HEAD {parsed.path or '/'} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
                        )
                        sock.recv(1)
                        row["http_response_start_ms"] = (
                            time.perf_counter_ns() - tls_end
                        ) / 1e6
            elif parsed.scheme == "http":
                raw.sendall(
                    f"HEAD {parsed.path or '/'} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
                )
                raw.recv(1)
                row["http_response_start_ms"] = (
                    time.perf_counter_ns() - connected
                ) / 1e6
        row["total_ms"] = (time.perf_counter_ns() - start) / 1e6
    except Exception as exc:  # noqa: BLE001 - record network failures
        row.update(
            status="error",
            error={"type": type(exc).__name__},
            total_ms=(time.perf_counter_ns() - start) / 1e6,
        )
    return row


async def websocket_measure(url: str, key: str, *, direct_openai: bool = False) -> dict:
    import websockets

    start = time.perf_counter_ns()
    row = {
        "request_start_utc": datetime.now(UTC).isoformat(),
        "status": "ok",
        "target_host": urlparse(url).hostname,
    }
    try:
        async with websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {key}"}
            if direct_openai
            else {"api-key": key},
            open_timeout=10,
        ):
            row["websocket_connect_ms"] = (time.perf_counter_ns() - start) / 1e6
        row["total_ms"] = (time.perf_counter_ns() - start) / 1e6
    except Exception as exc:  # noqa: BLE001 - record network failures
        row.update(
            status="error",
            error={"type": type(exc).__name__},
            total_ms=(time.perf_counter_ns() - start) / 1e6,
        )
    return row


async def http_reuse_measure(url: str) -> list[dict]:
    import httpx

    rows = []
    async with httpx.AsyncClient(timeout=10) as client:
        for connection in ("cold", "reused"):
            start = time.perf_counter_ns()
            try:
                response = await client.head(url)
                rows.append(
                    {
                        "status": "ok",
                        "connection": connection,
                        "http_status": response.status_code,
                        "http_head_response_ms": (time.perf_counter_ns() - start) / 1e6,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - network failures are data
                rows.append(
                    {
                        "status": "error",
                        "connection": connection,
                        "error": {"type": type(exc).__name__},
                    }
                )
    return rows


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()
    config = load_env()
    targets = {
        "azure_llm": config.get("AZURE_LLM_ENDPOINT"),
        "openai_llm": "https://api.openai.com/v1/models",
        "azure_realtime": config.get("AZURE_REALTIME_ENDPOINT"),
        "elevenlabs": "https://api.elevenlabs.io",
        "livekit": config.get("LIVEKIT_URL"),
        "backend": config.get("BACKEND_URL"),
    }
    path = create(
        __file__,
        manifest(
            "network",
            "multiple",
            None,
            None,
            config.get("AGENT_REGION"),
            args.runs
            * (
                sum(
                    3 if urlparse(value).scheme in ("http", "https") else 1
                    for value in targets.values()
                    if value
                )
                + bool(
                    config.get("AZURE_REALTIME_ENDPOINT")
                    and config.get("AZURE_REALTIME_API_KEY")
                    and config.get("AZURE_REALTIME_DEPLOYMENT")
                )
                + bool(
                    config.get("OPENAI_API_KEY") and config.get("OPENAI_REALTIME_MODEL")
                )
            ),
            0,
            {
                "targets": {
                    name: urlparse(value).hostname if value else None
                    for name, value in targets.items()
                },
                "target_regions": {
                    "azure_llm": config.get("AZURE_LLM_REGION"),
                    "azure_realtime": config.get("AZURE_REALTIME_REGION"),
                    "elevenlabs": config.get("ELEVENLABS_REGION"),
                    "livekit": config.get("LIVEKIT_REGION"),
                    "backend": config.get("BACKEND_REGION"),
                },
                "telnyx_media_path": "unavailable from benchmark host",
            },
        ),
    )
    rows = []
    for name, target in targets.items():
        if not target:
            continue
        for i in range(args.runs):
            row = await asyncio.to_thread(measure, target)
            row.update(target=name, run_index=i + 1, warmup=False)
            rows.append(row)
            append(path, "raw.jsonl", row)
            if row["status"] == "error":
                append(path, "errors.jsonl", row)
            if urlparse(target).scheme in ("http", "https"):
                for reuse_row in await http_reuse_measure(target):
                    reuse_row.update(target=name, run_index=i + 1, warmup=False)
                    rows.append(reuse_row)
                    append(path, "raw.jsonl", reuse_row)
            print(
                f"[{i + 1:02}/{args.runs:02}] {name} total={row['total_ms']:.1f}ms {row['status']}"
            )
    if (
        config.get("AZURE_REALTIME_ENDPOINT")
        and config.get("AZURE_REALTIME_API_KEY")
        and config.get("AZURE_REALTIME_DEPLOYMENT")
    ):
        from realtime.run import ws_url

        url = ws_url(
            config["AZURE_REALTIME_ENDPOINT"],
            config["AZURE_REALTIME_DEPLOYMENT"],
            config.get("AZURE_REALTIME_API_VERSION"),
        )
        for i in range(args.runs):
            row = await websocket_measure(url, config["AZURE_REALTIME_API_KEY"])
            row.update(target="azure_realtime_websocket", run_index=i + 1, warmup=False)
            rows.append(row)
            append(path, "raw.jsonl", row)
            if row["status"] == "error":
                append(path, "errors.jsonl", row)
    if config.get("OPENAI_API_KEY") and config.get("OPENAI_REALTIME_MODEL"):
        url = (
            "wss://api.openai.com/v1/realtime?model=" + config["OPENAI_REALTIME_MODEL"]
        )
        for i in range(args.runs):
            row = await websocket_measure(
                url, config["OPENAI_API_KEY"], direct_openai=True
            )
            row.update(
                target="openai_realtime_websocket", run_index=i + 1, warmup=False
            )
            rows.append(row)
            append(path, "raw.jsonl", row)
    finish(path, rows)


if __name__ == "__main__":
    asyncio.run(main())
