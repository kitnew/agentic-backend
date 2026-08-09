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

from ..models.google_sheets_append_execution_value_input_option import (
    GoogleSheetsAppendExecutionValueInputOption,
)
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.google_sheets_execution_idempotency import (
        GoogleSheetsExecutionIdempotency,
    )


T = TypeVar("T", bound="GoogleSheetsAppendExecution")


@_attrs_define
class GoogleSheetsAppendExecution:
    """
    Attributes:
        append_range (str):
        connection_id (UUID):
        idempotency (GoogleSheetsExecutionIdempotency):
        mapping_contract_version (Literal[1]):
        mapping_engine (Literal['jsonata-python']):
        mapping_engine_version (Literal['0.7.0']):
        mapping_language (Literal['jsonata']):
        plan_type (Literal['google_sheets.append_values.v1']):
        request_mapping (str):
        sheet_name (str):
        spreadsheet_id (str):
        value_input_option (GoogleSheetsAppendExecutionValueInputOption | Unset):  Default:
            GoogleSheetsAppendExecutionValueInputOption.RAW.
    """

    append_range: str
    connection_id: UUID
    idempotency: GoogleSheetsExecutionIdempotency
    mapping_contract_version: Literal[1]
    mapping_engine: Literal["jsonata-python"]
    mapping_engine_version: Literal["0.7.0"]
    mapping_language: Literal["jsonata"]
    plan_type: Literal["google_sheets.append_values.v1"]
    request_mapping: str
    sheet_name: str
    spreadsheet_id: str
    value_input_option: GoogleSheetsAppendExecutionValueInputOption | Unset = (
        GoogleSheetsAppendExecutionValueInputOption.RAW
    )

    def to_dict(self) -> dict[str, Any]:
        append_range = self.append_range

        connection_id = str(self.connection_id)

        idempotency = self.idempotency.to_dict()

        mapping_contract_version = self.mapping_contract_version

        mapping_engine = self.mapping_engine

        mapping_engine_version = self.mapping_engine_version

        mapping_language = self.mapping_language

        plan_type = self.plan_type

        request_mapping = self.request_mapping

        sheet_name = self.sheet_name

        spreadsheet_id = self.spreadsheet_id

        value_input_option: str | Unset = UNSET
        if not isinstance(self.value_input_option, Unset):
            value_input_option = self.value_input_option.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "append_range": append_range,
                "connection_id": connection_id,
                "idempotency": idempotency,
                "mapping_contract_version": mapping_contract_version,
                "mapping_engine": mapping_engine,
                "mapping_engine_version": mapping_engine_version,
                "mapping_language": mapping_language,
                "plan_type": plan_type,
                "request_mapping": request_mapping,
                "sheet_name": sheet_name,
                "spreadsheet_id": spreadsheet_id,
            }
        )
        if value_input_option is not UNSET:
            field_dict["value_input_option"] = value_input_option

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.google_sheets_execution_idempotency import (
            GoogleSheetsExecutionIdempotency,
        )

        d = dict(src_dict)
        append_range = d.pop("append_range")

        connection_id = UUID(d.pop("connection_id"))

        idempotency = GoogleSheetsExecutionIdempotency.from_dict(d.pop("idempotency"))

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

        plan_type = cast(Literal["google_sheets.append_values.v1"], d.pop("plan_type"))
        if plan_type != "google_sheets.append_values.v1":
            raise ValueError(
                f"plan_type must match const 'google_sheets.append_values.v1', got '{plan_type}'"
            )

        request_mapping = d.pop("request_mapping")

        sheet_name = d.pop("sheet_name")

        spreadsheet_id = d.pop("spreadsheet_id")

        _value_input_option = d.pop("value_input_option", UNSET)
        value_input_option: GoogleSheetsAppendExecutionValueInputOption | Unset
        if isinstance(_value_input_option, Unset):
            value_input_option = UNSET
        else:
            value_input_option = GoogleSheetsAppendExecutionValueInputOption(
                _value_input_option
            )

        google_sheets_append_execution = cls(
            append_range=append_range,
            connection_id=connection_id,
            idempotency=idempotency,
            mapping_contract_version=mapping_contract_version,
            mapping_engine=mapping_engine,
            mapping_engine_version=mapping_engine_version,
            mapping_language=mapping_language,
            plan_type=plan_type,
            request_mapping=request_mapping,
            sheet_name=sheet_name,
            spreadsheet_id=spreadsheet_id,
            value_input_option=value_input_option,
        )

        return google_sheets_append_execution
