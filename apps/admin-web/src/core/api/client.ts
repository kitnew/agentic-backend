import { normalizeApiError } from "./errors";

type GeneratedResponse = { data: unknown; status: number; headers: Headers };

export function responseData<T>(response: GeneratedResponse): T {
  if (response.status >= 200 && response.status < 300)
    return response.data as T;
  return throwAdminResponse(response);
}

export function throwAdminResponse(response: GeneratedResponse): never {
  throw normalizeApiError(response);
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  return normalizeApiError(error, fallback).message;
}
