export type ApiError = {
  status?: number;
  code?: string;
  message: string;
  requestId?: string;
  details?: unknown[];
};

const statusMessage: Record<number, string> = {
  400: "The request was invalid.",
  401: "Authentication is required.",
  403: "You do not have permission to perform this action.",
  404: "The requested resource was not found.",
  409: "The request conflicts with current server state.",
  412: "The configuration changed on the server.",
  422: "The submitted configuration is invalid.",
  500: "The server could not complete the request.",
};

function detailMessage(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map(detailMessage).find(Boolean) as string | undefined;
  if (typeof detail !== "object" || detail === null) return undefined;
  if ("message" in detail && typeof detail.message === "string")
    return detail.message;
  if ("msg" in detail && typeof detail.msg === "string") return detail.msg;
  return undefined;
}

export function normalizeApiError(
  input: unknown,
  fallback = "Request failed",
): ApiError {
  if (input instanceof Error && input.name === "TypeError")
    return { message: "Network request failed." };
  if (typeof input === "object" && input !== null) {
    const candidate = input as {
      status?: unknown;
      code?: unknown;
      message?: unknown;
      requestId?: unknown;
      details?: unknown;
      data?: unknown;
      headers?: Headers;
    };
    const status =
      typeof candidate.status === "number" ? candidate.status : undefined;
    const body = candidate.data ?? input;
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? body.detail
        : undefined;
    const details = Array.isArray(detail) ? detail : undefined;
    const error: ApiError = {
      status,
      code:
        typeof candidate.code === "string"
          ? candidate.code
          : typeof body === "object" &&
              body !== null &&
              "code" in body &&
              typeof body.code === "string"
            ? body.code
            : undefined,
      message:
        detailMessage(detail) ??
        (typeof candidate.message === "string"
          ? candidate.message
          : undefined) ??
        statusMessage[status ?? 0] ??
        fallback,
      requestId:
        candidate.headers?.get("x-request-id") ??
        (typeof candidate.requestId === "string"
          ? candidate.requestId
          : undefined),
    };
    if (details) error.details = details;
    return error;
  }
  return { message: fallback };
}

export async function normalizeResponseError(
  response: Response,
): Promise<ApiError> {
  let data: unknown;
  try {
    data = await response.clone().json();
  } catch {
    data = undefined;
  }
  return normalizeApiError(
    { data, headers: response.headers, status: response.status },
    response.statusText || statusMessage[response.status] || "Request failed",
  );
}

// Kept as a compatibility export for existing callers; normalization has one implementation.
export const toApiError = normalizeResponseError;
