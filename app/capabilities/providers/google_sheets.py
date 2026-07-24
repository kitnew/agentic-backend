from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from app.capabilities.schemas import (
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
    NewReservationRequest,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    RoomAvailabilityRequest,
    RoomAvailabilityResult,
    RoomAvailabilityStatus,
)
from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.schemas import (
    GoogleSheetsAppendRowRequest,
    GoogleSheetsReadRequest,
)
from app.tenants.schemas import (
    TenantAvailabilityConfig,
    TenantContext,
    spreadsheet_column_index,
    spreadsheet_column_span,
)
from app.tenants.policies import stay_nights


class GoogleSheetsSourceDataError(Exception):
    pass


class GoogleSheetsReservationProvider:
    provider_name = "google_sheets"

    def __init__(self, client: GoogleSheetsClient | None = None):
        self.client = client or GoogleSheetsClient()

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        if capability_request.name == "reservation.check_availability":
            return self._check_availability(tenant_context, capability_request)
        config = tenant_context.capabilities[capability_request.name].config
        if capability_request.name in {
            "reservation.change_request",
            "reservation.cancel_request",
        } or config.get("row_format") == "accommodation_request":
            return self._submit_reservation_request(tenant_context, capability_request)
        return self._create_reservation_request(tenant_context, capability_request)

    def _submit_reservation_request(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        models = {
            "reservation.create_request": NewReservationRequest,
            "reservation.change_request": ReservationChangeRequest,
            "reservation.cancel_request": ReservationCancellationRequest,
        }
        model = models[capability_request.name]
        try:
            request = model.model_validate(
                {
                    field: capability_request.input.get(field)
                    for field in model.model_fields
                    if field in capability_request.input
                }
            )
        except ValidationError:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.SKIPPED,
                provider="validation",
                user_message="Skontrolujte údaje žiadosti a potvrďte finálne detaily.",
                error="invalid_reservation_request",
            )

        if isinstance(request, ReservationChangeRequest) and request.affects_availability:
            availability = self._check_availability(
                tenant_context,
                CapabilityRequest(
                    name="reservation.check_availability",
                    input={
                        "check_in": request.check_in,
                        "check_out": request.check_out,
                        "room_type": request.room_type,
                        "room_count": request.room_count,
                    },
                    metadata=capability_request.metadata,
                ),
            )
            if availability.status != CapabilityStatus.SUCCESS or (
                availability.output or {}
            ).get("status") != RoomAvailabilityStatus.AVAILABLE.value:
                return CapabilityResult(
                    name=capability_request.name,
                    status=(
                        CapabilityStatus.FAILED
                        if availability.status == CapabilityStatus.FAILED
                        else CapabilityStatus.SKIPPED
                    ),
                    provider=availability.provider,
                    user_message=availability.user_message,
                    error=availability.error or "requested_stay_not_available",
                    output=availability.output,
                )

        config = tenant_context.capabilities[capability_request.name].config
        room_capacities = {
            room.code: room.capacity for room in tenant_context.business_info.room_types
        }
        rows = {
            "reservation.create_request": lambda value: [
                value.check_in.isoformat(),
                value.check_out.isoformat(),
                value.reservation_name,
                value.caller_number,
                value.reservation_phone,
                "",
                room_capacities[value.room_type],
                value.room_count,
                (
                    f"Allocated {value.room_type} at {value.requested_room_type} terms"
                    if value.requested_room_type
                    and value.requested_room_type != value.room_type
                    else ""
                ),
                False,
            ],
            "reservation.change_request": lambda value: [
                value.original_check_in.isoformat(),
                value.original_check_out.isoformat(),
                value.reservation_name,
                value.caller_number,
                value.reservation_phone,
                value.change,
                False,
            ],
            "reservation.cancel_request": lambda value: [
                value.original_check_in.isoformat(),
                value.original_check_out.isoformat(),
                value.reservation_name,
                value.caller_number,
                value.reservation_phone,
                value.reason,
                False,
            ],
        }
        try:
            append_result = self.client.append_row(
                GoogleSheetsAppendRowRequest(
                    spreadsheet_id=config["spreadsheet_id"],
                    sheet_name=config["sheet_name"],
                    values=rows[capability_request.name](request),
                )
            )
        except Exception as exc:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=self.provider_name,
                user_message="Žiadosť sa nepodarilo odoslať. Skúste to prosím neskôr.",
                error=str(exc),
            )

        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.SUCCESS,
            provider=self.provider_name,
            user_message="Vaša žiadosť bola odoslaná personálu na spracovanie.",
            output={
                "request_status": "submitted",
                "sheet_name": append_result.sheet_name,
                "row_appended": True,
                "updated_range": append_result.updated_range,
                "updated_rows": append_result.updated_rows,
                **(
                    {
                        "requested_room_type": request.requested_room_type
                        or request.room_type,
                        "allocated_room_type": request.room_type,
                        "fallback_applied": bool(
                            request.requested_room_type
                            and request.requested_room_type != request.room_type
                        ),
                    }
                    if isinstance(request, NewReservationRequest)
                    else {}
                ),
            },
        )

    def _check_availability(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        try:
            request = RoomAvailabilityRequest.model_validate(
                {
                    field: capability_request.input.get(field)
                    for field in ("check_in", "check_out", "room_type", "room_count")
                }
            )
        except ValidationError:
            return self._availability_failure(
                capability_request.name,
                "Invalid availability request.",
            )

        config = tenant_context.availability_config
        if not config or request.room_type not in config.room_type_columns:
            return self._availability_failure(
                capability_request.name,
                "Unsupported room type for tenant availability.",
            )

        try:
            table = self.client.read_values(
                GoogleSheetsReadRequest(
                    spreadsheet_id=config.spreadsheet_id,
                    sheet_name=config.sheet_name,
                    table_range=config.table_range,
                )
            ).values
            result = self._calculate_availability(table, config, request)
            if (
                result.status == RoomAvailabilityStatus.UNAVAILABLE
                and len(stay_nights(request.check_in, request.check_out)) == 1
            ):
                for fallback in config.one_night_room_type_fallbacks.get(
                    request.room_type, []
                ):
                    fallback_result = self._calculate_availability(
                        table, config, request.model_copy(update={"room_type": fallback})
                    )
                    if fallback_result.status == RoomAvailabilityStatus.AVAILABLE:
                        result = fallback_result.model_copy(
                            update={
                                "room_type": request.room_type,
                                "requested_room_type": request.room_type,
                                "allocated_room_type": fallback,
                                "fallback_applied": True,
                            }
                        )
                        break
        except GoogleSheetsSourceDataError as exc:
            return self._availability_failure(capability_request.name, str(exc))
        except Exception as exc:
            return self._availability_failure(
                capability_request.name,
                f"Availability source read failed ({exc.__class__.__name__}).",
            )

        messages = {
            RoomAvailabilityStatus.AVAILABLE: (
                "Podľa aktuálnych údajov je požadovaný počet izieb voľný. "
                "Izby tým nie sú rezervované ani blokované."
            ),
            RoomAvailabilityStatus.UNAVAILABLE: (
                "Požadovaný počet izieb nie je voľný počas celého termínu."
            ),
            RoomAvailabilityStatus.DATA_NOT_COVERED: (
                "Dostupnosť pre tento termín sa momentálne nedá spoľahlivo overiť. "
                "Kontaktujte prosím recepciu."
            ),
        }
        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.SUCCESS,
            provider=self.provider_name,
            user_message=messages[result.status],
            output=result.model_dump(mode="json"),
        )

    def _calculate_availability(
        self,
        table: list[list[Any]],
        config: TenantAvailabilityConfig,
        request: RoomAvailabilityRequest,
    ) -> RoomAvailabilityResult:
        table_start, table_end = spreadsheet_column_span(config.table_range)
        expected_width = table_end - table_start + 1
        date_index = spreadsheet_column_index(config.date_column) - table_start
        room_start, room_end = spreadsheet_column_span(
            config.room_type_columns[request.room_type]
        )
        room_indexes = set(range(room_start - table_start, room_end - table_start + 1))
        data_rows = table[config.data_start_row - 1 :]
        last_active = next(
            (
                index
                for index in range(len(data_rows) - 1, -1, -1)
                if any(not self._is_blank(value) for value in data_rows[index])
            ),
            -1,
        )

        free_rooms_by_date: dict[date, set[int]] = {}
        for offset, raw_row in enumerate(data_rows[: last_active + 1]):
            row_number = config.data_start_row + offset
            row = [*raw_row, *([""] * max(0, expected_width - len(raw_row)))]
            if self._is_blank(row[date_index]):
                raise GoogleSheetsSourceDataError(
                    f"Missing date in active availability row {row_number}."
                )
            row_date = self._parse_date(row[date_index], config.date_formats, row_number)
            if row_date in free_rooms_by_date:
                raise GoogleSheetsSourceDataError(
                    f"Duplicate availability date: {row_date.isoformat()}."
                )
            free_rooms_by_date[row_date] = {
                index for index in room_indexes if self._is_blank(row[index])
            }

        nights = stay_nights(request.check_in, request.check_out)
        if any(night not in free_rooms_by_date for night in nights):
            return RoomAvailabilityResult(
                status=RoomAvailabilityStatus.DATA_NOT_COVERED,
                room_type=request.room_type,
                requested_room_type=request.room_type,
                allocated_room_type=None,
                fallback_applied=False,
                check_in=request.check_in,
                check_out=request.check_out,
                requested_rooms=request.room_count,
                available_rooms=None,
            )

        continuously_free = set(room_indexes)
        for night in nights:
            continuously_free &= free_rooms_by_date[night]
        available_rooms = len(continuously_free)
        return RoomAvailabilityResult(
            status=(
                RoomAvailabilityStatus.AVAILABLE
                if available_rooms >= request.room_count
                else RoomAvailabilityStatus.UNAVAILABLE
            ),
            room_type=request.room_type,
            requested_room_type=request.room_type,
            allocated_room_type=(
                request.room_type
                if available_rooms >= request.room_count
                else None
            ),
            fallback_applied=False,
            check_in=request.check_in,
            check_out=request.check_out,
            requested_rooms=request.room_count,
            available_rooms=available_rooms,
        )

    def _parse_date(self, value: Any, formats: list[str], row_number: int) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_value = float(value)
            if numeric_value.is_integer():
                try:
                    return date(1899, 12, 30) + timedelta(days=int(numeric_value))
                except OverflowError:
                    pass
        if isinstance(value, str):
            for date_format in formats:
                try:
                    return datetime.strptime(value.strip(), date_format).date()
                except ValueError:
                    continue
        raise GoogleSheetsSourceDataError(
            f"Malformed date in availability row {row_number}."
        )

    def _is_blank(self, value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    def _availability_failure(self, name: str, error: str) -> CapabilityResult:
        return CapabilityResult(
            name=name,
            status=CapabilityStatus.FAILED,
            provider=self.provider_name,
            user_message=(
                "Dostupnosť sa momentálne nepodarilo overiť. "
                "Kontaktujte prosím recepciu."
            ),
            error=error,
        )

    def _create_reservation_request(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        config = tenant_context.capabilities[capability_request.name].config
        spreadsheet_id = config.get("spreadsheet_id")
        sheet_name = config.get("sheet_name")

        if not spreadsheet_id or not sheet_name:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=self.provider_name,
                user_message="Žiadosť sa nepodarilo uložiť. Skúste to prosím neskôr.",
                error="Google Sheets capability config requires spreadsheet_id and sheet_name.",
            )

        reservation_status = "pending_manual_confirmation"
        reservation_frame = capability_request.input.get("reservation_frame") or {}
        row = [
            datetime.now(timezone.utc).isoformat(),
            tenant_context.tenant_id,
            capability_request.input.get("message_id"),
            capability_request.input.get("conversation_id"),
            reservation_frame.get("guest_name"),
            reservation_frame.get("date"),
            reservation_frame.get("time"),
            reservation_frame.get("party_size"),
            reservation_frame.get("phone"),
            capability_request.input.get("raw_message"),
            reservation_status,
            capability_request.input.get("source_channel"),
        ]

        try:
            append_result = self.client.append_row(
                GoogleSheetsAppendRowRequest(
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=sheet_name,
                    values=row,
                )
            )
        except Exception as exc:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=self.provider_name,
                user_message="Žiadosť sa nepodarilo uložiť. Skúste to prosím neskôr.",
                error=str(exc),
            )

        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.SUCCESS,
            provider=self.provider_name,
            user_message="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí.",
            output={
                "spreadsheet_id": append_result.spreadsheet_id,
                "sheet_name": append_result.sheet_name,
                "row_appended": True,
                "updated_range": append_result.updated_range,
                "updated_rows": append_result.updated_rows,
                "reservation_status": reservation_status,
                "reservation_frame": reservation_frame,
            },
        )
