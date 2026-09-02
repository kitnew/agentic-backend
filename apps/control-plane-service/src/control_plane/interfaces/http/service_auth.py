from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

VOICE_AGENT = "voice-agent"
JOB_WORKER = "job-worker"
SERVICE_SCOPES = {
    VOICE_AGENT: frozenset({"runtime-secret:materialize"}),
    JOB_WORKER: frozenset({"integration-material:read"}),
}
_bearer = HTTPBearer(scheme_name="InternalServiceToken", auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


@dataclass(frozen=True, slots=True)
class ServicePrincipal:
    subject: str
    service: str
    scopes: frozenset[str]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "invalid bearer token",
        {"WWW-Authenticate": "Bearer"},
    )


def require_service_scope(scope: str) -> Callable[..., ServicePrincipal]:
    def dependency(request: Request, credentials: Credentials) -> ServicePrincipal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        try:
            unverified = jwt.decode(
                credentials.credentials,
                options={"verify_signature": False},
                algorithms=["HS256"],
            )
            service = unverified.get("service")
            if not isinstance(service, str) or service not in SERVICE_SCOPES:
                raise _unauthorized()
            settings = request.app.state.settings
            secret = {
                VOICE_AGENT: settings.voice_agent_service_secret.get_secret_value(),
                JOB_WORKER: settings.job_worker_service_secret.get_secret_value(),
            }[service]
            claims = jwt.decode(
                credentials.credentials,
                secret,
                algorithms=["HS256"],
                audience="control-plane-service",
                options={
                    "require": ["sub", "service", "aud", "iat", "exp", "scopes"],
                    "strict_aud": True,
                },
            )
        except InvalidTokenError as error:
            raise _unauthorized() from error
        subject, raw_scopes = claims["sub"], claims["scopes"]
        if (
            not isinstance(subject, str)
            or not subject
            or claims["service"] != service
            or not isinstance(raw_scopes, list)
            or not all(isinstance(item, str) for item in raw_scopes)
        ):
            raise _unauthorized()
        scopes = frozenset(raw_scopes)
        if not scopes <= SERVICE_SCOPES[service]:
            raise _unauthorized()
        if scope not in scopes:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"missing required scope: {scope}"
            )
        return ServicePrincipal(subject, service, scopes)

    return dependency
