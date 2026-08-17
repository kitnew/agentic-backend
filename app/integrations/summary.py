from openai import AsyncAzureOpenAI

from app.core.config import SummarySettings


SUMMARY_SYSTEM_PROMPT = (
    "Napíš stručné operatívne zhrnutie hovoru po slovensky. Uveď dôvod hovoru, "
    "každú žiadosť o novú rezerváciu, zmenu alebo zrušenie a nevyriešené otázky. "
    "Za úspešnú považuj iba akciu, ktorú agent v prepise výslovne označil za "
    "odoslanú alebo vykonanú. Odoslanú žiadosť nikdy neoznačuj ako potvrdenú "
    "rezerváciu. Nevymýšľaj chýbajúce údaje. Odpovedz iba zhrnutím."
)


class AzureSummaryClient:
    def __init__(self, settings: SummarySettings | None = None):
        self.settings = settings or SummarySettings.from_env()
        self.settings.validate()
        self.client = AsyncAzureOpenAI(
            api_key=self.settings.azure_api_key,
            azure_endpoint=self.settings.azure_endpoint,
            api_version=self.settings.azure_api_version,
        )

    async def summarize(self, transcript: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.azure_deployment,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Prepis hovoru:\n{transcript or '(bez zachytených správ)'}",
                },
            ],
        )
        summary = response.choices[0].message.content or ""
        if not summary.strip():
            raise RuntimeError("Post-call summary was empty")
        return summary.strip()
