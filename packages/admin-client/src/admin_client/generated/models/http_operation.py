from __future__ import annotations

from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.http_operation_method import HttpOperationMethod
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.expression_node import ExpressionNode
    from ..models.http_operation_headers import HttpOperationHeaders
    from ..models.http_operation_query_type_0 import HttpOperationQueryType0
    from ..models.http_request_spec import HttpRequestSpec
    from ..models.http_response_spec import HttpResponseSpec


T = TypeVar("T", bound="HttpOperation")


@_attrs_define
class HttpOperation:
    """
    Attributes:
        connection (str):
        method (HttpOperationMethod):
        timeout_seconds (float):
        headers (HttpOperationHeaders | Unset):
        path (ExpressionNode | None | str | Unset):
        query (HttpOperationQueryType0 | None | Unset):
        request (HttpRequestSpec | Unset):
        response (HttpResponseSpec | Unset):
        success_statuses (list[int] | None | Unset):
        type_ (Literal['http'] | Unset):  Default: 'http'.
    """

    connection: str
    method: HttpOperationMethod
    timeout_seconds: float
    headers: HttpOperationHeaders | Unset = UNSET
    path: ExpressionNode | None | str | Unset = UNSET
    query: HttpOperationQueryType0 | None | Unset = UNSET
    request: HttpRequestSpec | Unset = UNSET
    response: HttpResponseSpec | Unset = UNSET
    success_statuses: list[int] | None | Unset = UNSET
    type_: Literal["http"] | Unset = "http"

    def to_dict(self) -> dict[str, Any]:
        from ..models.expression_node import ExpressionNode
        from ..models.http_operation_query_type_0 import HttpOperationQueryType0

        connection = self.connection

        method = self.method.value

        timeout_seconds = self.timeout_seconds

        headers: dict[str, Any] | Unset = UNSET
        if not isinstance(self.headers, Unset):
            headers = self.headers.to_dict()

        path: dict[str, Any] | None | str | Unset
        if isinstance(self.path, Unset):
            path = UNSET
        elif isinstance(self.path, ExpressionNode):
            path = self.path.to_dict()
        else:
            path = self.path

        query: dict[str, Any] | None | Unset
        if isinstance(self.query, Unset):
            query = UNSET
        elif isinstance(self.query, HttpOperationQueryType0):
            query = self.query.to_dict()
        else:
            query = self.query

        request: dict[str, Any] | Unset = UNSET
        if not isinstance(self.request, Unset):
            request = self.request.to_dict()

        response: dict[str, Any] | Unset = UNSET
        if not isinstance(self.response, Unset):
            response = self.response.to_dict()

        success_statuses: list[int] | None | Unset
        if isinstance(self.success_statuses, Unset):
            success_statuses = UNSET
        elif isinstance(self.success_statuses, list):
            success_statuses = self.success_statuses

        else:
            success_statuses = self.success_statuses

        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "connection": connection,
                "method": method,
                "timeout_seconds": timeout_seconds,
            }
        )
        if headers is not UNSET:
            field_dict["headers"] = headers
        if path is not UNSET:
            field_dict["path"] = path
        if query is not UNSET:
            field_dict["query"] = query
        if request is not UNSET:
            field_dict["request"] = request
        if response is not UNSET:
            field_dict["response"] = response
        if success_statuses is not UNSET:
            field_dict["success_statuses"] = success_statuses
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.expression_node import ExpressionNode
        from ..models.http_operation_headers import HttpOperationHeaders
        from ..models.http_operation_query_type_0 import HttpOperationQueryType0
        from ..models.http_request_spec import HttpRequestSpec
        from ..models.http_response_spec import HttpResponseSpec

        d = dict(src_dict)
        connection = d.pop("connection")

        method = HttpOperationMethod(d.pop("method"))

        timeout_seconds = d.pop("timeout_seconds")

        _headers = d.pop("headers", UNSET)
        headers: HttpOperationHeaders | Unset
        if isinstance(_headers, Unset):
            headers = UNSET
        else:
            headers = HttpOperationHeaders.from_dict(_headers)

        def _parse_path(data: object) -> ExpressionNode | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                path_type_1 = ExpressionNode.from_dict(data)

                return path_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ExpressionNode | None | str | Unset, data)

        path = _parse_path(d.pop("path", UNSET))

        def _parse_query(data: object) -> HttpOperationQueryType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                query_type_0 = HttpOperationQueryType0.from_dict(data)

                return query_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(HttpOperationQueryType0 | None | Unset, data)

        query = _parse_query(d.pop("query", UNSET))

        _request = d.pop("request", UNSET)
        request: HttpRequestSpec | Unset
        if isinstance(_request, Unset):
            request = UNSET
        else:
            request = HttpRequestSpec.from_dict(_request)

        _response = d.pop("response", UNSET)
        response: HttpResponseSpec | Unset
        if isinstance(_response, Unset):
            response = UNSET
        else:
            response = HttpResponseSpec.from_dict(_response)

        def _parse_success_statuses(data: object) -> list[int] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                success_statuses_type_0 = cast(list[int], data)

                return success_statuses_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[int] | None | Unset, data)

        success_statuses = _parse_success_statuses(d.pop("success_statuses", UNSET))

        type_ = cast(Literal["http"] | Unset, d.pop("type", UNSET))
        if type_ != "http" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'http', got '{type_}'")

        http_operation = cls(
            connection=connection,
            method=method,
            timeout_seconds=timeout_seconds,
            headers=headers,
            path=path,
            query=query,
            request=request,
            response=response,
            success_statuses=success_statuses,
            type_=type_,
        )

        return http_operation
