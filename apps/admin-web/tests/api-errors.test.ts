import { describe, expect, it } from "vitest";

import { toApiError } from "../src/core/api/errors";

describe("API errors", () => {
  it("preserves safe backend detail, status, and request ID", async () => {
    const error = await toApiError(
      new Response(
        JSON.stringify({ detail: "access denied", code: "forbidden" }),
        {
          status: 403,
          statusText: "Forbidden",
          headers: {
            "content-type": "application/json",
            "x-request-id": "request-1",
          },
        },
      ),
    );
    expect(error).toEqual({
      status: 403,
      code: "forbidden",
      message: "access denied",
      requestId: "request-1",
    });
  });
});
