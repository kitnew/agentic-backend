import base64
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass
from typing import Any


class InvalidVoiceSessionToken(ValueError):
    pass


@dataclass(frozen=True)
class VoiceSessionClaims:
    tenant_id: str
    call_session_id: str
    language: str | None
    timezone: str
    iat: int
    exp: int
    conversation_id: str | None = None
    channel: str = "voice"
    mode: str = "manual"


class VoiceSessionTokenCodec:
    def __init__(self, secret: str):
        if len(secret.encode()) < 32 or not secret.strip():
            raise ValueError("voice session token secret must contain at least 32 bytes")
        self._secret = secret.encode()

    def encode(self, claims: VoiceSessionClaims) -> str:
        payload = {key: value for key, value in asdict(claims).items() if value is not None}
        encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = _b64(hmac.digest(self._secret, encoded.encode(), "sha256"))
        return f"{encoded}.{signature}"

    def decode(self, token: str, *, now: int | None = None) -> VoiceSessionClaims:
        try:
            payload_part, signature_part = token.split(".")
            expected = hmac.digest(self._secret, payload_part.encode(), "sha256")
            if not hmac.compare_digest(expected, _unb64(signature_part)):
                raise InvalidVoiceSessionToken("invalid token signature")
            payload: dict[str, Any] = json.loads(_unb64(payload_part))
            claims = VoiceSessionClaims(**payload)
        except InvalidVoiceSessionToken:
            raise
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise InvalidVoiceSessionToken("malformed session token") from exc

        current = int(time.time()) if now is None else now
        if (
            not isinstance(claims.tenant_id, str)
            or not claims.tenant_id
            or not isinstance(claims.call_session_id, str)
            or not claims.call_session_id
            or (claims.conversation_id is not None and not isinstance(claims.conversation_id, str))
            or (claims.language is not None and not isinstance(claims.language, str))
            or not isinstance(claims.timezone, str)
            or not claims.timezone
            or type(claims.iat) is not int
            or type(claims.exp) is not int
            or claims.channel != "voice"
            or claims.mode not in {"manual", "call"}
            or claims.iat > current
            or claims.exp <= current
            or claims.exp <= claims.iat
        ):
            raise InvalidVoiceSessionToken("invalid or expired session token")
        return claims


class VoiceRuntimeAuthenticator:
    def __init__(self, codec: VoiceSessionTokenCodec):
        self._codec = codec

    def authenticate(self, subprotocols: list[str]) -> VoiceSessionClaims:
        if len(subprotocols) != 2 or subprotocols[0] != "voice-session":
            raise InvalidVoiceSessionToken("voice-session subprotocol is required")
        return self._codec.decode(subprotocols[1])


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
