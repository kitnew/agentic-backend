import aiohttp

from app.contracts.livekit import (
    ExecuteLiveKitToolRequest,
    ExecuteLiveKitToolResponse,
    PersistLiveKitMessageRequest,
    PersistLiveKitMessageResponse,
)


class BackendCoreClient:
    def __init__(self, base_url: str, token: str, session: aiohttp.ClientSession | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        self._owns_session = session is None

    async def persist_message(
        self,
        *,
        role: str,
        content: str,
        turn_id: str,
        item_id: str,
        interrupted: bool = False,
    ) -> dict:
        response = await self._post(
            "/api/v1/voice/livekit/messages",
            PersistLiveKitMessageRequest(
                role=role,
                content=content,
                turn_id=turn_id,
                item_id=item_id,
                interrupted=interrupted,
            ),
        )
        return PersistLiveKitMessageResponse.model_validate(response).model_dump()

    async def execute_tool(
        self,
        *,
        capability: str,
        arguments: dict,
        turn_id: str,
        tool_call_id: str,
    ) -> dict:
        response = await self._post(
            "/api/v1/voice/livekit/tools",
            ExecuteLiveKitToolRequest(
                capability=capability,
                arguments=arguments,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
            ),
        )
        return ExecuteLiveKitToolResponse.model_validate(response).model_dump()

    async def _post(self, path: str, payload) -> dict:
        async with self.session.post(
            f"{self.base_url}{path}",
            json=payload.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {self.token}"},
        ) as response:
            body = await response.json()
            if response.status >= 400:
                raise RuntimeError(body.get("detail") or f"Backend Core HTTP {response.status}")
            return body

    async def aclose(self) -> None:
        if self._owns_session:
            await self.session.close()
