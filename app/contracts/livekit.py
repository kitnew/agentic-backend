import base64
import hmac
import json
import time
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.voice import VoiceTurnConfig, VoiceTurnOverrides


Identifier = Annotated[str, Field(min_length=1, max_length=128)]
ShortText = Annotated[str, Field(min_length=1, max_length=1_000)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateLiveKitSessionRequest(ContractModel):
    tenant_id: Identifier
    conversation_id: Identifier | None = None
    turn_overrides: VoiceTurnOverrides | None = None


class LiveKitSessionResponse(ContractModel):
    runtime: Literal["livekit"] = "livekit"
    call_session_id: Identifier
    conversation_id: Identifier
    room_name: Identifier
    livekit_url: Annotated[str, Field(min_length=1, max_length=2_048)]
    participant_token: Annotated[str, Field(min_length=1, max_length=65_536)]
    turn_config: VoiceTurnConfig


class SessionChatMessage(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=32_768)]


class RuntimeToolDefinition(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    public_name: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    ]
    description: ShortText
    parameters: dict[str, Any]
    backend_capability: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.-]+$")
    ]
    enabled: bool = True
    inject_caller_number: bool = False
    argument_container: Identifier | None = None

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object" or not isinstance(value.get("properties"), dict):
            raise ValueError("tool parameters must be an object JSON schema")
        if len(_canonical_json(value).encode()) > 32_768:
            raise ValueError("tool parameter schema is too large")
        return value


class LiveKitJobMetadata(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    tenant_id: Identifier
    call_session_id: Identifier
    conversation_id: Identifier
    channel: Literal["voice"]
    language: Annotated[str, Field(min_length=1, max_length=32)]
    timezone: Annotated[str, Field(min_length=1, max_length=128)]
    instructions: Annotated[str, Field(min_length=1, max_length=65_536)]
    greeting: Annotated[str, Field(min_length=1, max_length=2_048)] | None = None
    tools: tuple[RuntimeToolDefinition, ...] = Field(default=(), max_length=32)
    end_call_enabled: bool = False
    chat_history: tuple[SessionChatMessage, ...] = Field(default=(), max_length=200)
    stt_language: Annotated[str, Field(min_length=1, max_length=32)]
    tts_voice_id: Identifier
    tts_model: Identifier
    tts_language: Annotated[str, Field(min_length=1, max_length=32)]
    turn_config: VoiceTurnConfig

    @classmethod
    def parse_job(cls, raw: str) -> "LiveKitJobMetadata":
        if not raw or len(raw.encode()) > 256_000:
            raise ValueError("LiveKit job metadata is empty or too large")
        return cls.model_validate_json(raw)


class PersistLiveKitMessageRequest(ContractModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=32_768)]
    turn_id: Identifier
    item_id: Identifier
    interrupted: bool = False


class PersistLiveKitMessageResponse(ContractModel):
    message_id: Identifier
    status: Identifier


class ExecuteLiveKitToolRequest(ContractModel):
    capability: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.-]+$")
    ]
    arguments: dict[str, Any]
    turn_id: Identifier
    tool_call_id: Identifier

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(_canonical_json(value).encode()) > 65_536:
            raise ValueError("tool arguments are too large")
        return value

    @property
    def request_fingerprint(self) -> str:
        import hashlib

        return hashlib.sha256(
            _canonical_json(
                {"capability": self.capability, "arguments": self.arguments}
            ).encode()
        ).hexdigest()


class ExecuteLiveKitToolResponse(ContractModel):
    status: Literal["pending", "success", "failed", "disabled", "skipped"]
    message: Annotated[str, Field(max_length=8_192)] | None = None
    error: Annotated[str, Field(max_length=8_192)] | None = None
    result: dict[str, Any] | None = None
    tool_call_id: Identifier | None = None


class FinalizeLiveKitCallRequest(ContractModel):
    call_session_id: Identifier
    outcome: Literal["completed", "failed"]
    reason: Annotated[str, Field(max_length=2_048)] | None = None
    error: Annotated[str, Field(max_length=8_192)] | None = None
    livekit_job_id: Identifier | None = None
    caller_phone: Annotated[str, Field(max_length=128)] | None = None


class FinalizeLiveKitCallResponse(ContractModel):
    call_session_id: Identifier
    call_status: Literal["completed", "failed"]
    finalization_status: Literal["pending", "processing", "completed", "failed"]
    queued: bool = False
    transcript_sheet_range: Annotated[str, Field(max_length=512)] | None = None
    error: Annotated[str, Field(max_length=8_192)] | None = None


class SessionAccessClaims(ContractModel):
    subject: Identifier
    tenant_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=100)
    iat: int
    exp: int
    audience: Literal["livekit-session"] = "livekit-session"

    @model_validator(mode="after")
    def validate_times_and_tenants(self):
        if self.exp <= self.iat or len(self.tenant_ids) != len(set(self.tenant_ids)):
            raise ValueError("invalid session access claims")
        return self


class InvalidSessionAccessToken(ValueError):
    pass


class SessionAccessTokenCodec:
    def __init__(self, secret: str):
        if len(secret.encode()) < 32 or not secret.strip():
            raise ValueError("LiveKit session access secret must contain at least 32 bytes")
        self._secret = secret.encode()

    def encode(self, claims: SessionAccessClaims) -> str:
        payload = _b64(claims.model_dump_json().encode())
        signature = _b64(hmac.digest(self._secret, payload.encode(), "sha256"))
        return f"{payload}.{signature}"

    def decode(self, token: str, *, now: int | None = None) -> SessionAccessClaims:
        try:
            if not token or len(token) > 8_192:
                raise InvalidSessionAccessToken("invalid token size")
            payload_part, signature_part = token.split(".")
            expected = hmac.digest(self._secret, payload_part.encode(), "sha256")
            signature = _unb64(signature_part)
            if _b64(signature) != signature_part or not hmac.compare_digest(expected, signature):
                raise InvalidSessionAccessToken("invalid token signature")
            claims = SessionAccessClaims.model_validate_json(_unb64(payload_part))
        except InvalidSessionAccessToken:
            raise
        except Exception as exc:
            raise InvalidSessionAccessToken("malformed token") from exc
        current = int(time.time()) if now is None else now
        if claims.iat > current or claims.exp <= current:
            raise InvalidSessionAccessToken("invalid or expired token")
        return claims


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


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON serializable") from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
