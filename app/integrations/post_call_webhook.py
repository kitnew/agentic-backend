import os

import aiohttp


async def send_post_call_webhook(
    config,
    payload: dict,
    *,
    session=None,
    timeout_seconds: float = 15,
    idempotency_key: str | None = None,
) -> None:
    if not config.webhook_url:
        return
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key
        or f"post-call:{payload['data']['conversation_id']}:{payload['type']}",
    }
    if config.webhook_api_key_env:
        api_key = os.getenv(config.webhook_api_key_env, "")
        if api_key:
            headers["x-make-apikey"] = api_key
    owns_session = session is None
    session = session or aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_seconds)
    )
    try:
        async with session.post(config.webhook_url, json=payload, headers=headers) as response:
            if response.status >= 400:
                raise RuntimeError(f"post_call_webhook_http_{response.status}")
    finally:
        if owns_session:
            await session.close()
