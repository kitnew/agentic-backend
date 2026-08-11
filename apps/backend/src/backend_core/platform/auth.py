from collections.abc import Callable
from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

VOICE_AGENT = "voice-agent"
JOB_WORKER = "job-worker"
SERVICE_SCOPES = {
    VOICE_AGENT: frozenset(
        {
            "tenant-config:read",
            "tenant-routing:resolve",
            "call-session:create",
            "call-session:runtime-context:read",
            "call-session:activate",
            "call-session:complete",
            "call-session:fail",
            "call-session:observe",
            "conversation-message:append",
            "capability-invocation:create",
            "capability-invocation:read",
        }
    ),
    JOB_WORKER: frozenset(
        {
            "capability-result:write",
            "finalization-context:read",
            "post-call-action:read",
        }
    ),
}

admin_bearer = HTTPBearer(scheme_name="AdminToken", auto_error=False)
internal_bearer = HTTPBearer(scheme_name="InternalServiceToken", auto_error=False)
AdminCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(admin_bearer),
]
InternalCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(internal_bearer),
]


@dataclass(frozen=True)
class ServicePrincipal:
    subject: str
    service: str
    scopes: frozenset[str]


def unauthorized(detail: str = "invalid bearer token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(
    request: Request,
    credentials: AdminCredentials,
) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    expected = request.app.state.settings.admin_api_token.get_secret_value()
    if not compare_digest(credentials.credentials, expected):
        raise unauthorized()


def require_internal_scope(scope: str) -> Callable[..., ServicePrincipal]:
    def dependency(
        request: Request,
        credentials: InternalCredentials,
    ) -> ServicePrincipal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise unauthorized()

        settings = request.app.state.settings
        token = credentials.credentials
        try:
            unverified = jwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["HS256"],
            )
            service = unverified.get("service")
            if not isinstance(service, str):
                raise unauthorized()
            secrets = {
                VOICE_AGENT: settings.voice_agent_service_secret.get_secret_value(),
                JOB_WORKER: settings.job_worker_service_secret.get_secret_value(),
            }
            secret = secrets.get(service)
            if secret is None:
                raise unauthorized()
            claims = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=settings.internal_api_audience,
                options={
                    "require": ["sub", "service", "aud", "iat", "exp", "scopes"],
                    "strict_aud": True,
                },
            )
        except InvalidTokenError as error:
            raise unauthorized() from error

        subject = claims["sub"]
        raw_scopes = claims["scopes"]
        if (
            not isinstance(subject, str)
            or not subject
            or claims["service"] != service
            or not isinstance(raw_scopes, list)
            or not all(isinstance(item, str) for item in raw_scopes)
        ):
            raise unauthorized()

        scopes = frozenset(raw_scopes)
        if not scopes <= SERVICE_SCOPES[service]:
            raise unauthorized()
        if scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing required scope: {scope}",
            )
        return ServicePrincipal(subject=subject, service=service, scopes=scopes)

    return dependency
