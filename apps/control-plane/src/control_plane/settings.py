import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    api_url: str
    token: str

    @classmethod
    def load(cls, api_url: str | None = None) -> Settings:
        raw_url = api_url or os.environ.get("AGENTCTL_API_URL")
        if not raw_url:
            raise SettingsError("AGENTCTL_API_URL is required")
        raw_url = raw_url.strip()
        try:
            parsed = urlsplit(raw_url)
            _ = parsed.port
        except ValueError as error:
            raise SettingsError("AGENTCTL_API_URL is invalid") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise SettingsError("AGENTCTL_API_URL must be an HTTP(S) origin")

        token = os.environ.get("AGENTCTL_TOKEN")
        if not token:
            raise SettingsError("AGENTCTL_TOKEN is required by the current Admin API")
        return cls(api_url=raw_url.rstrip("/"), token=token)
