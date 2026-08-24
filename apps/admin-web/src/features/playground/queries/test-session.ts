import { throwAdminResponse } from "../../../core/api/client";
import {
  createTestVoiceSessionAdminV1VoiceTestSessionsPost,
  getTestVoiceSessionAdminV1VoiceTestSessionsCallIdGet,
} from "../../../core/api/generated/admin-voice/admin-voice";
import type {
  CallLifecycleResponse,
  CreateTestVoiceSessionResponse,
} from "../../../core/api/generated/models";

export async function createTestSession(
  tenantId: string,
  options?: RequestInit,
): Promise<CreateTestVoiceSessionResponse> {
  const response = await createTestVoiceSessionAdminV1VoiceTestSessionsPost(
    { tenant_id: tenantId },
    {
      ...options,
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
        ...options?.headers,
      },
    },
  );
  if (response.status === 201) return response.data;
  return throwAdminResponse(response);
}

export async function getTestSession(
  callId: string,
  options?: RequestInit,
): Promise<CallLifecycleResponse> {
  const response = await getTestVoiceSessionAdminV1VoiceTestSessionsCallIdGet(
    callId,
    options,
  );
  if (response.status === 200) return response.data;
  return throwAdminResponse(response);
}
