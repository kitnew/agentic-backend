export type ApiError = {
  status?: number;
  code?: string;
  message: string;
  requestId?: string;
};

export async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("x-request-id") ?? undefined;
  let message = response.statusText || "Request failed";
  let code: string | undefined;
  try {
    const body: unknown = await response.clone().json();
    if (typeof body === "object" && body !== null) {
      const detail = "detail" in body ? body.detail : undefined;
      if (typeof detail === "string") message = detail;
      if (
        typeof detail === "object" &&
        detail !== null &&
        "message" in detail &&
        typeof detail.message === "string"
      )
        message = detail.message;
      if ("code" in body && typeof body.code === "string") code = body.code;
    }
  } catch {
    /* Non-JSON errors retain HTTP status text. */
  }
  return { status: response.status, code, message, requestId };
}
