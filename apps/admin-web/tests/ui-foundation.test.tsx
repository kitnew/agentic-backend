import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthoringValidation } from "../src/core/configuration/authoring";
import {
  FormGrid,
  FormSection,
  ResourceStatus,
  type ResourceStatusValue,
  TechnicalDiagnostics,
  WorkspaceHeader,
} from "../src/core/ui/foundation";

describe("FormSection", () => {
  it.each([
    [true, true],
    [false, false],
  ])("uses defaultExpanded=%s", (defaultExpanded, visible) => {
    render(
      <FormSection defaultExpanded={defaultExpanded} title="LLM">
        <p>Model settings</p>
      </FormSection>,
    );
    expect(screen.getByRole("button", { name: "LLM" })).toHaveAttribute(
      "aria-expanded",
      String(defaultExpanded),
    );
    expect(screen.queryByText("Model settings") !== null).toBe(visible);
  });

  it("toggles independently and ignores header actions", async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    render(
      <FormSection
        headerActions={
          <button onClick={action} type="button">
            Enable override
          </button>
        }
        title="LLM"
      >
        <p>Model settings</p>
      </FormSection>,
    );
    const toggle = screen.getByRole("button", { name: "LLM" });

    await user.click(screen.getByRole("button", { name: "Enable override" }));
    expect(action).toHaveBeenCalledOnce();
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Model settings")).not.toBeInTheDocument();
  });
});

describe("AuthoringValidation", () => {
  const error = {
    code: "invalid",
    path: "llm.model",
    message: "Unsupported model",
  };
  const warning = {
    code: "warning",
    path: "integration",
    message: "Not ready",
  };

  it("stays hidden without actionable issues", () => {
    const { container } = render(<AuthoringValidation />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [[error], [], "Errors"],
    [[], [warning], "Warnings"],
    [[error], [warning], "Configuration needs attention"],
  ])("renders errors=%j warnings=%j", (errors, warnings, visible) => {
    render(<AuthoringValidation errors={errors} warnings={warnings} />);
    expect(screen.getByText(visible as string)).toBeVisible();
  });
});

describe("ResourceStatus", () => {
  it.each<ResourceStatusValue>([
    "Published",
    "Saved · Pending publish",
    "Unsaved changes",
    "Saving…",
    "Conflict",
    "Degraded",
    "Not configured",
  ])("renders %s consistently", (status) => {
    render(<ResourceStatus status={status} />);
    expect(screen.getByRole("status")).toHaveAttribute("data-status", status);
    expect(screen.getByText(status)).toBeVisible();
  });
});

it("FormGrid exposes responsive column structure", () => {
  const { container } = render(
    <FormGrid>
      <div>Model</div>
      <div>Reasoning</div>
    </FormGrid>,
  );
  expect(container.firstChild).toHaveAttribute("data-columns", "2");
  expect(container.firstChild).toHaveClass("sm:grid-cols-2");
});

it("TechnicalDiagnostics is collapsed by default and expands", async () => {
  const user = userEvent.setup();
  render(
    <TechnicalDiagnostics>
      <pre>{`{"inbound_trunk_id":"ST_inbound"}`}</pre>
    </TechnicalDiagnostics>,
  );
  const details = screen.getByText("Technical diagnostics").closest("details");
  expect(details).not.toHaveAttribute("open");
  await user.click(screen.getByText("Technical diagnostics"));
  expect(details).toHaveAttribute("open");
  expect(screen.getByText(/inbound_trunk_id/)).toBeVisible();
});

describe("WorkspaceHeader", () => {
  it("renders title, status, and primary action", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    render(
      <WorkspaceHeader
        primaryAction={{ label: "Save", onClick: save }}
        status="Published"
        title="Runtime"
      />,
    );
    expect(screen.getByRole("heading", { name: "Runtime" })).toBeVisible();
    expect(screen.getByText("Published")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(save).toHaveBeenCalledOnce();
  });

  it("uses real disabled and loading action states", () => {
    const { rerender } = render(
      <WorkspaceHeader
        primaryAction={{ disabled: true, label: "Save", onClick: vi.fn() }}
        title="Agent"
      />,
    );
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    rerender(
      <WorkspaceHeader
        primaryAction={{
          label: "Save",
          loading: true,
          loadingLabel: "Saving…",
          onClick: vi.fn(),
        }}
        title="Agent"
      />,
    );
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  });
});
