from datetime import datetime, timezone

import pytest

from app.capabilities.providers.google_sheets import GoogleSheetsReservationProvider
from app.capabilities.registry import CapabilityRegistry
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest
from app.integrations.google_sheets.schemas import (
    GoogleSheetsAppendRowResult,
    GoogleSheetsReadResult,
)
from app.tenants.loader import TenantConfigLoader


class Sheets:
    def __init__(self, values=None):
        self.reads = []
        self.appends = []
        self.values = values or [
            ["header"] * 31,
            ["2026-08-29"] + [""] * 30,
            ["2026-08-30"] + [""] * 30,
        ]

    def read_values(self, request):
        self.reads.append(request)
        return GoogleSheetsReadResult(values=self.values)

    def append_row(self, request):
        self.appends.append(request)
        return GoogleSheetsAppendRowResult(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            updated_range=f"{request.sheet_name}!A2",
            updated_rows=1,
        )


def request(name, **changes):
    common = {
        "reservation_name": "Ján Novák",
        "caller_number": "+421900111222",
        "reservation_phone": "+421900333444",
        "confirmed": True,
    }
    values = {
        "reservation.create_request": {
            **common,
            "check_in": "2026-08-29",
            "check_out": "2026-08-31",
            "room_type": "two_bed",
            "room_count": 2,
        },
        "reservation.change_request": {
            **common,
            "original_check_in": "2026-08-29",
            "original_check_out": "2026-08-31",
            "change": "Prosím o detskú postieľku.",
        },
        "reservation.cancel_request": {
            **common,
            "original_check_in": "2026-08-29",
            "original_check_out": "2026-08-31",
            "reason": "Zmena plánov",
        },
    }[name]
    return CapabilityRequest(name=name, input={**values, **changes})


def routed(name, sheets, *, hour=12, **changes):
    registry = CapabilityRegistry()
    registry.providers["google_sheets"] = GoogleSheetsReservationProvider(sheets)
    return CapabilityRouter(
        registry, clock=lambda: datetime(2026, 7, 21, hour, tzinfo=timezone.utc)
    ).execute(TenantConfigLoader().load("penzion_grand"), request(name, **changes))


@pytest.mark.parametrize(
    ("room_type", "room_code"),
    [("two_bed", 2), ("three_bed", 3), ("four_bed", 4)],
)
def test_new_request_maps_row_without_implicitly_checking_availability(
    room_type, room_code
):
    sheets = Sheets()

    result = routed("reservation.create_request", sheets, room_type=room_type)

    assert result.status == "success"
    assert result.output["request_status"] == "submitted"
    assert sheets.reads == []
    assert sheets.appends[0].sheet_name == "reservations_new"
    assert sheets.appends[0].values == [
        "2026-08-29",
        "2026-08-31",
        "Ján Novák",
        "+421900111222",
        "+421900333444",
        "",
        room_code,
        2,
        "",
        False,
    ]


@pytest.mark.parametrize(
    ("name", "sheet", "tail"),
    [
        (
            "reservation.change_request",
            "reservations_change",
            ["Prosím o detskú postieľku.", False],
        ),
        ("reservation.cancel_request", "reservations_cancel", ["Zmena plánov", False]),
    ],
)
def test_change_and_cancellation_map_rows_without_availability(name, sheet, tail):
    sheets = Sheets()

    result = routed(name, sheets, hour=23)

    assert result.status == "success"
    assert sheets.reads == []
    assert sheets.appends[0].sheet_name == sheet
    assert sheets.appends[0].values == [
        "2026-08-29",
        "2026-08-31",
        "Ján Novák",
        "+421900111222",
        "+421900333444",
        *tail,
    ]


def test_availability_affecting_change_reuses_availability_check():
    sheets = Sheets()

    result = routed(
        "reservation.change_request",
        sheets,
        check_in="2026-08-29",
        check_out="2026-08-31",
        room_type="three_bed",
        room_count=1,
    )

    assert result.status == "success"
    assert len(sheets.reads) == 1


def test_fallback_room_type_and_original_terms_are_written():
    sheets = Sheets()

    result = routed(
        "reservation.create_request",
        sheets,
        room_type="three_bed",
        requested_room_type="two_bed",
        room_count=1,
    )

    assert result.status == "success"
    assert sheets.reads == []
    assert sheets.appends[0].values[6:9] == [
        3,
        1,
        "Allocated three_bed at two_bed terms",
    ]
    assert result.output["allocated_room_type"] == "three_bed"
    assert result.output["requested_room_type"] == "two_bed"
    assert result.output["fallback_applied"] is True


def test_cancellation_without_reason_writes_empty_note():
    sheets = Sheets()

    result = routed("reservation.cancel_request", sheets, reason="")

    assert result.status == "success"
    assert sheets.appends[0].values[-2:] == ["", False]


@pytest.mark.parametrize(
    ("name", "changes", "error"),
    [
        ("reservation.create_request", {"confirmed": False}, "invalid_reservation_request"),
        ("reservation.create_request", {"reservation_phone": "z volaného"}, "invalid_reservation_request"),
        ("reservation.create_request", {"check_in": "2026-07-20"}, "past_check_in_not_allowed"),
    ],
)
def test_new_request_validation_prevents_writes(name, changes, error):
    sheets = Sheets()

    result = routed(name, sheets, **changes)

    assert result.error == error
    assert sheets.reads == []
    assert sheets.appends == []


def test_only_new_requests_are_blocked_at_22_local():
    sheets = Sheets()

    result = routed("reservation.create_request", sheets, hour=20)

    assert result.error == "reservation_cutoff_reached"
    assert sheets.reads == []
    assert sheets.appends == []
