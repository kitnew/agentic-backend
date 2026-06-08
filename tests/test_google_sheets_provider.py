from app.capabilities.providers.google_sheets import GoogleSheetsReservationProvider
from app.capabilities.schemas import CapabilityRequest
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowResult
from app.tenants.loader import TenantConfigLoader


class FakeGoogleSheetsClient:
    def __init__(self):
        self.requests = []

    def append_row(self, request):
        self.requests.append(request)
        return GoogleSheetsAppendRowResult(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            updated_range="test!A2:G2",
            updated_rows=1,
        )


def test_google_sheets_provider_can_be_mocked():
    client = FakeGoogleSheetsClient()
    tenant_context = TenantConfigLoader().load("demo_restaurant")
    provider = GoogleSheetsReservationProvider(client)

    result = provider.execute(
        tenant_context,
        CapabilityRequest(
            name="reservation.create_request",
            input={
                "raw_message": "Chcem urobit rezervaciu.",
                "message_id": "message-1",
                "conversation_id": "conversation-1",
                "source_channel": "chat",
            },
        ),
    )

    assert result.status == "success"
    assert result.provider == "google_sheets"
    assert result.output["row_appended"] is True
    assert client.requests[0].values[2] == "message-1"
