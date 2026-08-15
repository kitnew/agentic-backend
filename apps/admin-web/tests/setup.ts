import "@testing-library/jest-dom/vitest";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";

import { queryClient } from "../src/app/query-client";

export const server = setupServer();
Object.defineProperty(window, "scrollTo", {
  value: () => undefined,
  writable: true,
});

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  queryClient.clear();
});
afterAll(() => server.close());
