import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import type {
  AuthoringPlan,
  AuthoringState,
} from "../src/core/api/generated/models";
import { router } from "../src/routes/router";
import { server } from "./setup";

const tenantId = "11111111-1111-4111-8111-111111111111";
const tenant = {
  id: tenantId,
  slug: "demo",
  display_name: "Demo tenant",
  business_type: "hotel",
  status: "active",
  active_release_id: "published",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

afterEach(() => cleanup());

describe.each([
  {
    name: "Prompt",
    path: "prompt",
    readPath: "prompt",
    planPath: "prompt",
    initial: { text: "Initial prompt" },
    edit: "Canonical prompt",
    expected: "Canonical prompt",
    label: "Prompt",
  },
  {
    name: "Knowledge Base",
    path: "knowledge-base",
    readPath: "knowledge",
    planPath: "knowledge",
    initial: { content: "Initial knowledge" },
    edit: "Canonical knowledge",
    expected: "Canonical knowledge",
    label: "Knowledge Base",
  },
])("tenant $name authoring editor", (resource) => {
  it("uses plan, saves the authoring DTO, refetches canonical state, and has no Publish", async () => {
    const user = userEvent.setup();
    const plan = vi.fn();
    const save = vi.fn();
    let state: AuthoringState = {
      value: resource.initial,
      published_value: resource.initial,
      source: "published",
      etag: null,
    };
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(
        `/admin/v1/tenants/${tenantId}/authoring/${resource.readPath}`,
        () => HttpResponse.json(state),
      ),
      http.post(
        `/admin/v1/tenants/${tenantId}/authoring/${resource.planPath}/plan`,
        async ({ request }) => {
          plan(await request.json());
          return HttpResponse.json({ valid: true, errors: [], warnings: [] });
        },
      ),
      http.put(
        `/admin/v1/tenants/${tenantId}/authoring/${resource.readPath}`,
        async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          save(body);
          const value =
            resource.readPath === "prompt"
              ? { text: String(body.text).trim() }
              : resource.readPath === "knowledge"
                ? { content: String(body.content).trim() }
                : body;
          state = {
            value,
            published_value: resource.initial,
            source: "draft",
            etag: '"1"',
          };
          return HttpResponse.json(state);
        },
      ),
    );
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/${resource.path}` as never,
    });

    const editor = await screen.findByLabelText(resource.label);
    expect(plan).not.toHaveBeenCalled();
    expect(screen.queryByText("Validating changes…")).not.toBeInTheDocument();
    fireEvent.change(editor, { target: { value: resource.edit } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(plan).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledOnce();
    expect(screen.getByLabelText(resource.label)).toHaveValue(
      resource.expected,
    );
    expect(await screen.findByText("Saved · Pending publish")).toBeVisible();
    expect(screen.queryByText("Validating changes…")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Publish" }),
    ).not.toBeInTheDocument();
  });
});

describe("tenant authoring validation lifecycle", () => {
  function installRuntimeHandlers(
    planResponse: AuthoringPlan | Promise<Response>,
    initial: Record<string, unknown> = { llm: { model: "gpt-4o" } },
    save?: (value: unknown) => void,
  ) {
    let state: AuthoringState = {
      value: initial,
      published_value: initial,
      source: "published",
      etag: null,
    };
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(`/admin/v1/tenants/${tenantId}/authoring/runtime`, () =>
        HttpResponse.json(state),
      ),
      http.get(`/admin/v1/tenants/${tenantId}/authoring/knowledge`, () =>
        HttpResponse.json({
          value: { content: "" },
          published_value: { content: "" },
          source: "published",
          etag: null,
        }),
      ),
      http.post(`/admin/v1/tenants/${tenantId}/authoring/runtime/plan`, () =>
        planResponse instanceof Promise
          ? planResponse
          : HttpResponse.json(planResponse),
      ),
      http.put(
        `/admin/v1/tenants/${tenantId}/authoring/runtime`,
        async ({ request }) => {
          const value = (await request.json()) as Record<string, unknown>;
          save?.(value);
          state = {
            value,
            published_value: initial,
            source: "draft",
            etag: '"1"',
          };
          return HttpResponse.json(state);
        },
      ),
    );
  }

  it("uses typed controls for the complete runtime authoring contract", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    installRuntimeHandlers(
      { valid: true, errors: [], warnings: [] },
      {
        llm: {
          model: "gpt-5.6-terra",
          temperature: null,
          reasoning_effort: "none",
        },
        tts: { voice_id: "9Nd358gE1q0p0pDh8FgP" },
      },
      save,
    );
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/runtime` as never,
    });

    expect((await screen.findAllByRole("checkbox"))[0]).toBeChecked();
    expect(screen.getByLabelText(/Model/)).toHaveValue("gpt-5.6-terra");
    expect(screen.getByLabelText(/Reasoning effort/)).toHaveValue("none");
    expect(screen.getByLabelText(/Temperature/)).toHaveValue(null);
    expect(screen.getAllByRole("checkbox")[1]).toBeChecked();
    await user.click(screen.getByRole("button", { name: /TTS override/ }));
    expect(screen.getByLabelText(/Voice ID/)).toHaveValue(
      "9Nd358gE1q0p0pDh8FgP",
    );
    expect(
      screen.queryByLabelText("Runtime configuration"),
    ).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText(/Model/));
    await user.type(screen.getByLabelText(/Model/), "gpt-5.6-terra-updated");
    await user.selectOptions(screen.getByLabelText(/Reasoning effort/), "high");
    await user.clear(screen.getByLabelText(/Temperature/));
    await user.type(screen.getByLabelText(/Temperature/), "0.5");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved · Pending publish")).toBeVisible();
    expect(save).toHaveBeenCalledWith({
      llm: {
        model: "gpt-5.6-terra-updated",
        reasoning_effort: "high",
        temperature: 0.5,
      },
      tts: { voice_id: "9Nd358gE1q0p0pDh8FgP" },
    });
  });

  it("keeps background validation quiet and enables Save after a valid plan", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    let resolvePlan!: (response: Response) => void;
    const planResponse = new Promise<Response>((resolve) => {
      resolvePlan = resolve;
    });
    installRuntimeHandlers(planResponse, undefined, save);
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/runtime` as never,
    });

    const editor = await screen.findByLabelText(/Model/);
    expect(screen.queryByText("Validating changes…")).not.toBeInTheDocument();
    fireEvent.change(editor, {
      target: { value: "gpt-4.1" },
    });
    expect(screen.queryByText(/Validating/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Validating latest changes…")).toBeVisible();

    resolvePlan(HttpResponse.json({ valid: true, errors: [], warnings: [] }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(screen.queryByText("Validating changes…")).not.toBeInTheDocument();
  });

  it("preserves a newer edit made while Save is pending", async () => {
    const user = userEvent.setup();
    let state: AuthoringState = {
      value: { llm: { model: "gpt-4o" } },
      published_value: { llm: { model: "gpt-4o" } },
      source: "published",
      etag: null,
    };
    let resolvePut!: () => void;
    let resolvePutStarted!: () => void;
    const putReleased = new Promise<void>((resolve) => {
      resolvePut = resolve;
    });
    const putStarted = new Promise<void>((resolve) => {
      resolvePutStarted = resolve;
    });
    const saved = vi.fn();
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(`/admin/v1/tenants/${tenantId}/authoring/runtime`, () =>
        HttpResponse.json(state),
      ),
      http.post(`/admin/v1/tenants/${tenantId}/authoring/runtime/plan`, () =>
        HttpResponse.json({ valid: true, errors: [], warnings: [] }),
      ),
      http.put(
        `/admin/v1/tenants/${tenantId}/authoring/runtime`,
        async ({ request }) => {
          const value = await request.json();
          saved(value);
          resolvePutStarted();
          await putReleased;
          state = {
            value,
            published_value: { llm: { model: "gpt-4o" } },
            source: "draft",
            etag: '"1"',
          };
          return HttpResponse.json(state);
        },
      ),
    );
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/runtime` as never,
    });
    const editor = await screen.findByLabelText(/Model/);
    fireEvent.change(editor, { target: { value: "gpt-4.1" } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await putStarted;
    fireEvent.change(editor, { target: { value: "gpt-5" } });
    resolvePut();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    expect(saved).toHaveBeenCalledWith({ llm: { model: "gpt-4.1" } });
    expect(editor).toHaveValue("gpt-5");
    expect(screen.getByText("Unsaved changes")).toBeVisible();
  });

  it.each([
    {
      name: "blocking errors",
      response: {
        valid: false,
        errors: [{ code: "invalid", path: "llm", message: "Invalid model" }],
        warnings: [],
      },
      visible: "llm: Invalid model",
      enabled: false,
    },
    {
      name: "warnings",
      response: {
        valid: true,
        errors: [],
        warnings: [{ code: "warning", path: "llm", message: "Check model" }],
      },
      visible: "llm: Check model",
      enabled: true,
    },
  ])("handles plan $name without stale clean validation", async (caseData) => {
    installRuntimeHandlers(caseData.response);
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/runtime` as never,
    });
    const editor = await screen.findByLabelText(/Model/);
    fireEvent.change(editor, {
      target: { value: "gpt-4.1" },
    });
    expect(await screen.findByText(caseData.visible)).toBeVisible();
    if (caseData.enabled)
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
      );
    else expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("hides the candidate plan when the editor is reverted to canonical", async () => {
    installRuntimeHandlers({ valid: true, errors: [], warnings: [] });
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/runtime` as never,
    });
    const editor = await screen.findByLabelText(/Model/);
    fireEvent.change(editor, {
      target: { value: "gpt-4.1" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    fireEvent.change(editor, {
      target: { value: "gpt-4o" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeDisabled(),
    );
    expect(screen.queryByText("Validating changes…")).not.toBeInTheDocument();
  });

  it("blocks Save and shows a plan request failure", async () => {
    installRuntimeHandlers(
      Promise.resolve(new Response(null, { status: 500 })),
    );
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/runtime` as never,
    });
    const editor = await screen.findByLabelText(/Model/);
    fireEvent.change(editor, {
      target: { value: "gpt-4.1" },
    });
    expect(
      await screen.findByText("Backend validation could not be completed."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
