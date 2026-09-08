from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.http_semantic_execution_input_method import (
    HttpSemanticExecutionInputMethod,
)
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.expr_node import ExprNode
    from ..models.http_request_spec_input import HttpRequestSpecInput
    from ..models.http_response_spec_input import HttpResponseSpecInput
    from ..models.http_semantic_execution_input_headers import (
        HttpSemanticExecutionInputHeaders,
    )
    from ..models.http_semantic_execution_input_query_type_0 import (
        HttpSemanticExecutionInputQueryType0,
    )


T = TypeVar("T", bound="HttpSemanticExecutionInput")


@_attrs_define
class HttpSemanticExecutionInput:
    """
    Attributes:
        integration_key (str):
        method (HttpSemanticExecutionInputMethod):
        request (HttpRequestSpecInput):
        response (HttpResponseSpecInput):
        timeout_seconds (float):
        headers (HttpSemanticExecutionInputHeaders | Unset):
        path (ExprNode | None | str | Unset):
        query (HttpSemanticExecutionInputQueryType0 | None | Unset):
        success_statuses (list[int] | None | Unset):
    """

    integration_key: str
    method: HttpSemanticExecutionInputMethod
    request: HttpRequestSpecInput
    response: HttpResponseSpecInput
    timeout_seconds: float
    headers: HttpSemanticExecutionInputHeaders | Unset = UNSET
    path: ExprNode | None | str | Unset = UNSET
    query: HttpSemanticExecutionInputQueryType0 | None | Unset = UNSET
    success_statuses: list[int] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.expr_node import ExprNode
        from ..models.http_semantic_execution_input_query_type_0 import (
            HttpSemanticExecutionInputQueryType0,
        )

        integration_key = self.integration_key

        method = self.method.value

        request = self.request.to_dict()

        response = self.response.to_dict()

        timeout_seconds = self.timeout_seconds

        headers: dict[str, Any] | Unset = UNSET
        if not isinstance(self.headers, Unset):
            headers = self.headers.to_dict()

        path: dict[str, Any] | None | str | Unset
        if isinstance(self.path, Unset):
            path = UNSET
        elif isinstance(self.path, ExprNode):
            path = self.path.to_dict()
        else:
            path = self.path

        query: dict[str, Any] | None | Unset
        if isinstance(self.query, Unset):
            query = UNSET
        elif isinstance(self.query, HttpSemanticExecutionInputQueryType0):
            query = self.query.to_dict()
        else:
            query = self.query

        success_statuses: list[int] | None | Unset
        if isinstance(self.success_statuses, Unset):
            success_statuses = UNSET
        elif isinstance(self.success_statuses, list):
            success_statuses = self.success_statuses

        else:
            success_statuses = self.success_statuses

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "integration_key": integration_key,
                "method": method,
                "request": request,
                "response": response,
                "timeout_seconds": timeout_seconds,
            }
        )
        if headers is not UNSET:
            field_dict["headers"] = headers
        if path is not UNSET:
            field_dict["path"] = path
        if query is not UNSET:
            field_dict["query"] = query
        if success_statuses is not UNSET:
            field_dict["success_statuses"] = success_statuses

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.expr_node import ExprNode
        from ..models.http_request_spec_input import HttpRequestSpecInput
        from ..models.http_response_spec_input import HttpResponseSpecInput
        from ..models.http_semantic_execution_input_headers import (
            HttpSemanticExecutionInputHeaders,
        )
        from ..models.http_semantic_execution_input_query_type_0 import (
            HttpSemanticExecutionInputQueryType0,
        )

        d = dict(src_dict)
        integration_key = d.pop("integration_key")

        method = HttpSemanticExecutionInputMethod(d.pop("method"))

        request = HttpRequestSpecInput.from_dict(d.pop("request"))

        response = HttpResponseSpecInput.from_dict(d.pop("response"))

        timeout_seconds = d.pop("timeout_seconds")

        _headers = d.pop("headers", UNSET)
        headers: HttpSemanticExecutionInputHeaders | Unset
        if isinstance(_headers, Unset):
            headers = UNSET
        else:
            headers = HttpSemanticExecutionInputHeaders.from_dict(_headers)

        def _parse_path(data: object) -> ExprNode | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                path_type_1 = ExprNode.from_dict(data)

                return path_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ExprNode | None | str | Unset, data)

        path = _parse_path(d.pop("path", UNSET))

        def _parse_query(
            data: object,
        ) -> HttpSemanticExecutionInputQueryType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                query_type_0 = HttpSemanticExecutionInputQueryType0.from_dict(data)

                return query_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(HttpSemanticExecutionInputQueryType0 | None | Unset, data)

        query = _parse_query(d.pop("query", UNSET))

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

        http_semantic_execution_input = cls(
            integration_key=integration_key,
            method=method,
            request=request,
            response=response,
            timeout_seconds=timeout_seconds,
            headers=headers,
            path=path,
            query=query,
            success_statuses=success_statuses,
        )

        return http_semantic_execution_input
