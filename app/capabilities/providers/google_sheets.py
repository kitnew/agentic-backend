from datetime import datetime, timezone

from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowRequest
from app.tenants.schemas import TenantContext


class GoogleSheetsReservationProvider:
    provider_name = "google_sheets"

    def __init__(self, client: GoogleSheetsClient | None = None):
        self.client = client or GoogleSheetsClient()

    def execute(
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
