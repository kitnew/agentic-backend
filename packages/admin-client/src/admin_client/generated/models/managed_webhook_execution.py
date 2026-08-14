from __future__ import annotations

from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    cast,
)
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.managed_webhook_response_config import ManagedWebhookResponseConfig


T = TypeVar("T", bound="ManagedWebhookExecution")


@_attrs_define
class ManagedWebhookExecution:
    """
    Attributes:
        connection_id (UUID):
        mapping_contract_version (Literal[1]):
        mapping_engine (Literal['jsonata-python']):
        mapping_engine_version (Literal['0.7.0']):
        mapping_language (Literal['jsonata']):
        plan_type (Literal['managed_webhook.post_json.v1']):
        request_mapping (str):
        timeout_seconds (int):
        response (ManagedWebhookResponseConfig | None | Unset):
    """

    connection_id: UUID
    mapping_contract_version: Literal[1]
    mapping_engine: Literal["jsonata-python"]
    mapping_engine_version: Literal["0.7.0"]
    mapping_language: Literal["jsonata"]
    plan_type: Literal["managed_webhook.post_json.v1"]
    request_mapping: str
    timeout_seconds: int
    response: ManagedWebhookResponseConfig | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.managed_webhook_response_config import (
            ManagedWebhookResponseConfig,
        )

        connection_id = str(self.connection_id)

        mapping_contract_version = self.mapping_contract_version

        mapping_engine = self.mapping_engine

        mapping_engine_version = self.mapping_engine_version

        mapping_language = self.mapping_language

        plan_type = self.plan_type

        request_mapping = self.request_mapping

        timeout_seconds = self.timeout_seconds

        response: dict[str, Any] | None | Unset
        if isinstance(self.response, Unset):
            response = UNSET
        elif isinstance(self.response, ManagedWebhookResponseConfig):
            response = self.response.to_dict()
        else:
            response = self.response

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "connection_id": connection_id,
                "mapping_contract_version": mapping_contract_version,
                "mapping_engine": mapping_engine,
                "mapping_engine_version": mapping_engine_version,
                "mapping_language": mapping_language,
                "plan_type": plan_type,
                "request_mapping": request_mapping,
                "timeout_seconds": timeout_seconds,
            }
        )
        if response is not UNSET:
            field_dict["response"] = response

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.managed_webhook_response_config import (
            ManagedWebhookResponseConfig,
        )

        d = dict(src_dict)
        connection_id = UUID(d.pop("connection_id"))

        mapping_contract_version = cast(Literal[1], d.pop("mapping_contract_version"))
        if mapping_contract_version != 1:
            raise ValueError(
                f"mapping_contract_version must match const 1, got '{mapping_contract_version}'"
            )

        mapping_engine = cast(Literal["jsonata-python"], d.pop("mapping_engine"))
        if mapping_engine != "jsonata-python":
            raise ValueError(
                f"mapping_engine must match const 'jsonata-python', got '{mapping_engine}'"
            )

        mapping_engine_version = cast(Literal["0.7.0"], d.pop("mapping_engine_version"))
        if mapping_engine_version != "0.7.0":
            raise ValueError(
                f"mapping_engine_version must match const '0.7.0', got '{mapping_engine_version}'"
            )

        mapping_language = cast(Literal["jsonata"], d.pop("mapping_language"))
        if mapping_language != "jsonata":
            raise ValueError(
                f"mapping_language must match const 'jsonata', got '{mapping_language}'"
            )

        plan_type = cast(Literal["managed_webhook.post_json.v1"], d.pop("plan_type"))
        if plan_type != "managed_webhook.post_json.v1":
            raise ValueError(
                f"plan_type must match const 'managed_webhook.post_json.v1', got '{plan_type}'"
            )

        request_mapping = d.pop("request_mapping")

        timeout_seconds = d.pop("timeout_seconds")

        def _parse_response(
            data: object,
        ) -> ManagedWebhookResponseConfig | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_type_0 = ManagedWebhookResponseConfig.from_dict(data)

                return response_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManagedWebhookResponseConfig | None | Unset, data)

        response = _parse_response(d.pop("response", UNSET))

        managed_webhook_execution = cls(
            connection_id=connection_id,
            mapping_contract_version=mapping_contract_version,
            mapping_engine=mapping_engine,
            mapping_engine_version=mapping_engine_version,
            mapping_language=mapping_language,
            plan_type=plan_type,
            request_mapping=request_mapping,
            timeout_seconds=timeout_seconds,
            response=response,
        )

        return managed_webhook_execution
