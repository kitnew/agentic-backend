import json
import os
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.tenants.schemas import TenantContext


class MakeWebhookProvider:
    provider_name = "make_webhook"
    default_timeout_seconds = 15

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        config = tenant_context.capabilities[capability_request.name].config
        if not valid_webhook_config(config):
            return self._failure(capability_request.name, "invalid_webhook_config")
        url = config.get("webhook_url")
        timeout = config.get("timeout_seconds", self.default_timeout_seconds)
        payload = {
            "tenant_id": tenant_context.tenant_id,
            "capability": capability_request.name,
            "input": capability_request.input,
            "metadata": capability_request.metadata or {},
        }
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        api_key_env = config.get("webhook_api_key_env")
        if api_key_env and (api_key := os.getenv(api_key_env)):
            headers["x-make-apikey"] = api_key
        if idempotency_key := (capability_request.metadata or {}).get("idempotency_key"):
            headers["Idempotency-Key"] = idempotency_key

        try:
            with urlopen(  # noqa: S310 - URL is tenant-admin configuration
                Request(
                    url,
                    data=json.dumps(payload, default=str).encode("utf-8"),
                    headers=headers,
                    method="POST",
                ),
                timeout=timeout,
            ) as response:
                status = response.status
                body = response.read()
        except (socket.timeout, TimeoutError):
            return self._failure(capability_request.name, "webhook_timeout")
        except HTTPError as exc:
            return self._failure(capability_request.name, f"webhook_http_{exc.code}")
        except (OSError, URLError) as exc:
            return self._failure(
                capability_request.name,
                f"webhook_request_failed:{exc.__class__.__name__}",
            )

        if status >= 400:
            return self._failure(capability_request.name, f"webhook_http_{status}")

        try:
            response_payload: Any = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._failure(capability_request.name, "invalid_webhook_response")

        if not isinstance(response_payload, dict):
            response_payload = {"response": response_payload}
        response_status = response_payload.get("status")
        if isinstance(response_status, str):
            response_status = response_status.casefold()
        result_status = {
            "skipped": CapabilityStatus.SKIPPED,
            "failed": CapabilityStatus.FAILED,
            "error": CapabilityStatus.FAILED,
        }.get(response_status, CapabilityStatus.SUCCESS)
        output = response_payload.get("output", response_payload or None)
        if output is not None and not isinstance(output, dict):
            output = {"response": output}
        default_message = (
            "Žiadosť sa nepodarilo odoslať. Skúste to prosím neskôr."
            if result_status == CapabilityStatus.FAILED
            else "Vaša žiadosť bola odoslaná personálu na spracovanie."
        )
        user_message = response_payload.get("user_message")
        if not isinstance(user_message, str):
            user_message = default_message
        error = response_payload.get("error")
        if error is not None and not isinstance(error, str):
            error = str(error)
        return CapabilityResult(
            name=capability_request.name,
            status=result_status,
            provider=self.provider_name,
            output=output,
            user_message=user_message,
            error=error,
        )

    def _failure(self, name: str, error: str) -> CapabilityResult:
        return CapabilityResult(
            name=name,
            status=CapabilityStatus.FAILED,
            provider=self.provider_name,
            user_message="Žiadosť sa nepodarilo odoslať. Skúste to prosím neskôr.",
            error=error,
        )


def valid_webhook_config(config: dict[str, Any]) -> bool:
    url = config.get("webhook_url")
    parsed = urlparse(url) if isinstance(url, str) else None
    timeout = config.get("timeout_seconds", MakeWebhookProvider.default_timeout_seconds)
    return bool(
        parsed
        and parsed.scheme in {"http", "https"}
        and parsed.netloc
        and isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
        and timeout > 0
    )
