from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HttpAuthenticationNone(ContractModel):
    type: Literal["none"] = "none"


class HttpApiKeyHeaderAuthentication(ContractModel):
    type: Literal["api_key_header"] = "api_key_header"
    header_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9-]{0,63}$")


HttpAuthentication = Annotated[
    HttpAuthenticationNone | HttpApiKeyHeaderAuthentication,
    Field(discriminator="type"),
]


RESERVED_HTTP_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "x-operation-id", "content-type", "authorization"}
)


class HttpConnectionSecurity(ContractModel):
    additional_allowed_hosts: list[str] = Field(default_factory=list, max_length=50)


class HttpConnectionConfiguration(ContractModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict, max_length=50)
    authentication: HttpAuthentication
    security: HttpConnectionSecurity = Field(default_factory=HttpConnectionSecurity)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("endpoint must be an absolute HTTPS URL without userinfo or fragment")
        if parsed.port not in {None, 443}:
            raise ValueError("endpoint port is not allowed")
        return value

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        seen: set[str] = set()
        for name, header_value in value.items():
            normalized = name.lower()
            if normalized in RESERVED_HTTP_HEADERS:
                raise ValueError(f"reserved header: {name}")
            if normalized in seen or not name or any(ch in name for ch in "\r\n:") or any(ch in header_value for ch in "\r\n"):
                raise ValueError("invalid HTTP header")
            seen.add(normalized)
        return value

    @model_validator(mode="after")
    def authentication_header_is_not_static(self) -> HttpConnectionConfiguration:
        if self.authentication.type == "api_key_header" and self.authentication.header_name.lower() in {key.lower() for key in self.headers}:
            raise ValueError("authentication header cannot be static")
        return self
