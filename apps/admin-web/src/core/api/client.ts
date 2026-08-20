import type { ApiError } from "./errors";

type GeneratedResponse = { data: unknown; status: number; headers: Headers };

export function responseData<T>(response: GeneratedResponse): T {
  if (response.status >= 200 && response.status < 300)
    return response.data as T;
  return throwAdminResponse(response);
}

export function throwAdminResponse(response: GeneratedResponse): never {
  const detail =
    typeof response.data === "object" &&
    response.data !== null &&
    "detail" in response.data
      ? response.data.detail
      : undefined;
  const message =
    typeof detail === "string" ? detail : `Request failed (${response.status})`;
  const error: ApiError = {
    status: response.status,
    message,
    requestId: response.headers.get("x-request-id") ?? undefined,
  };
  throw error;
}
