import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  EmptyState,
  PageError,
  PageLoading,
} from "../src/components/page-states";

describe("platform page states", () => {
  it("renders loading, error retry, and empty states", async () => {
    const retry = vi.fn();
    render(
      <>
        <PageLoading />
        <PageError title="Failed" onRetry={retry} />
        <EmptyState title="Nothing here" />
      </>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    await screen.getByRole("button", { name: "Retry" }).click();
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.getByText("Nothing here")).toBeVisible();
  });
});
