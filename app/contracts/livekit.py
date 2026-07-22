import base64
import hmac
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.voice.latency import VoiceTurnConfig, VoiceTurnOverrides


class CreateLiveKitSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    conversation_id: str | None = None
    turn_overrides: VoiceTurnOverrides | None = None


class LiveKitSessionResponse(BaseModel):
    runtime: Literal["livekit"] = "livekit"
    call_session_id: str
    conversation_id: str
    room_name: str
    livekit_url: str
    participant_token: str
    turn_config: VoiceTurnConfig


class PersistLiveKitMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str
    turn_id: str
    item_id: str
    interrupted: bool = False


class PersistLiveKitMessageResponse(BaseModel):
    message_id: str
    status: str


class ExecuteLiveKitToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str
    arguments: dict
    turn_id: str
    tool_call_id: str


class ExecuteLiveKitToolResponse(BaseModel):
    status: str
    message: str | None = None
    error: str | None = None
    result: dict | None = None
    tool_call_id: str | None = None


class InvalidLiveKitBackendToken(ValueError):
    pass


@dataclass(frozen=True)
class LiveKitBackendClaims:
    tenant_id: str
    call_session_id: str
    conversation_id: str
    language: str | None
    timezone: str
    iat: int
    exp: int
    channel: Literal["voice"] = "voice"


class LiveKitBackendTokenCodec:
    def __init__(self, secret: str):
        if len(secret.encode()) < 32 or not secret.strip():
            raise ValueError("LiveKit backend token secret must contain at least 32 bytes")
        self._secret = secret.encode()

    def encode(self, claims: LiveKitBackendClaims) -> str:
        payload = {key: value for key, value in asdict(claims).items() if value is not None}
        encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = _b64(hmac.digest(self._secret, encoded.encode(), "sha256"))
        return f"{encoded}.{signature}"

    def decode(self, token: str, *, now: int | None = None) -> LiveKitBackendClaims:
        try:
            payload_part, signature_part = token.split(".")
            expected = hmac.digest(self._secret, payload_part.encode(), "sha256")
            signature = _unb64(signature_part)
            if _b64(signature) != signature_part or not hmac.compare_digest(expected, signature):
                raise InvalidLiveKitBackendToken("invalid token signature")
            payload: dict[str, Any] = json.loads(_unb64(payload_part))
            claims = LiveKitBackendClaims(**payload)
        except InvalidLiveKitBackendToken:
            raise
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise InvalidLiveKitBackendToken("malformed token") from exc

        current = int(time.time()) if now is None else now
        if (
            not isinstance(claims.tenant_id, str)
            or not claims.tenant_id
            or not isinstance(claims.call_session_id, str)
            or not claims.call_session_id
            or not isinstance(claims.conversation_id, str)
            or not claims.conversation_id
            or (claims.language is not None and not isinstance(claims.language, str))
            or not isinstance(claims.timezone, str)
            or not claims.timezone
            or type(claims.iat) is not int
            or type(claims.exp) is not int
            or claims.channel != "voice"
            or claims.iat > current
            or claims.exp <= current
            or claims.exp <= claims.iat
        ):
            raise InvalidLiveKitBackendToken("invalid or expired token")
        return claims


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
