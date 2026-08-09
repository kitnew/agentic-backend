from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.call_lifecycle_status import CallLifecycleStatus

T = TypeVar("T", bound="CallLifecycleResponse")


@_attrs_define
class CallLifecycleResponse:
    """
    Attributes:
        call_session_id (UUID):
        ended_at (datetime.datetime | None):
        failure_reason (None | str):
        started_at (datetime.datetime | None):
        status (CallLifecycleStatus):
    """

    call_session_id: UUID
    ended_at: datetime.datetime | None
    failure_reason: None | str
    started_at: datetime.datetime | None
    status: CallLifecycleStatus

    def to_dict(self) -> dict[str, Any]:
        call_session_id = str(self.call_session_id)

        ended_at: None | str
        if isinstance(self.ended_at, datetime.datetime):
            ended_at = self.ended_at.isoformat()
        else:
            ended_at = self.ended_at

        failure_reason: None | str
        failure_reason = self.failure_reason

        started_at: None | str
        if isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        status = self.status.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "call_session_id": call_session_id,
                "ended_at": ended_at,
                "failure_reason": failure_reason,
                "started_at": started_at,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        call_session_id = UUID(d.pop("call_session_id"))

        def _parse_ended_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                ended_at_type_0 = datetime.datetime.fromisoformat(data)

                return ended_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        ended_at = _parse_ended_at(d.pop("ended_at"))

        def _parse_failure_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        failure_reason = _parse_failure_reason(d.pop("failure_reason"))

        def _parse_started_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = datetime.datetime.fromisoformat(data)

                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        started_at = _parse_started_at(d.pop("started_at"))

        status = CallLifecycleStatus(d.pop("status"))

        call_lifecycle_response = cls(
            call_session_id=call_session_id,
            ended_at=ended_at,
            failure_reason=failure_reason,
            started_at=started_at,
            status=status,
        )

        return call_lifecycle_response
