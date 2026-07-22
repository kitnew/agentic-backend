import time

from fastapi import Header, HTTPException

from app.contracts.livekit import (
    InvalidSessionAccessToken,
    SessionAccessClaims,
    SessionAccessTokenCodec,
)
from app.core.config import SessionAuthSettings


def authenticate_session_access(
    authorization: str = Header(default=""),
    x_livekit_debug_auth: str = Header(default=""),
) -> SessionAccessClaims:
    settings = SessionAuthSettings.from_env()
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid session authentication")
        try:
            return SessionAccessTokenCodec(settings.secret).decode(
                authorization.removeprefix("Bearer ")
            )
        except (ValueError, InvalidSessionAccessToken) as exc:
            raise HTTPException(status_code=401, detail="Invalid session authentication") from exc

    if (
        x_livekit_debug_auth == "debug-chat"
        and settings.debug_available
    ):
        now = int(time.time())
        return SessionAccessClaims(
            subject="debug-chat",
            tenant_ids=settings.debug_tenant_ids,
            iat=now,
            exp=now + 300,
        )
    if x_livekit_debug_auth == "debug-chat":
        raise HTTPException(
            status_code=401,
            detail=(
                "Debug session access is disabled; set APP_ENV=development, "
                "LIVEKIT_DEBUG_AUTH_ENABLED=true, and LIVEKIT_DEBUG_ALLOWED_TENANTS"
            ),
        )
    raise HTTPException(status_code=401, detail="Session authentication is required")
