import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import { router } from "../src/routes/router";
import { runtimePolicy } from "./platform-fixtures";
import { server } from "./setup";

const baseState = {
  runtime_draft: null,
  system_prompt_draft: null,
  profile_prompt_drafts: {},
  active_release: {
    id: "release",
    release_number: 3,
    runtime_revision_id: "runtime",
    system_prompt_revision_id: "system",
  },
  active_runtime: runtimePolicy,
  active_system_prompt: "System canonical",
  active_profile_prompts: { active_only: "Active prompt" },
};

describe("Platform resource pages", () => {
  beforeEach(() => {
    server.use(http.get("/admin/v1/tenants", () => HttpResponse.json([])));
  });

  it("edits typed Runtime, keeps collapse local, plans, saves, and refetches canonical state", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    const state = structuredClone(baseState);
    server.use(
      http.get("/admin/v1/platform/components/state", () =>
        HttpResponse.json(state),
      ),
      http.post("/admin/v1/platform/components/runtime/plan", () =>
        HttpResponse.json({
          valid: true,
          errors: [],
          warnings: [{ code: "notice", message: "Review model" }],
        }),
      ),
      http.put(
        "/admin/v1/platform/components/runtime/draft",
        async ({ request }) => {
          const body = (await request.json()) as {
            policy: typeof runtimePolicy;
          };
          save(body.policy);
          state.runtime_draft = {
            id: "draft",
            version: 1,
            value: {
              ...body.policy,
              llm: { ...body.policy.llm, model: "normalized-model" },
            },
          } as never;
          return HttpResponse.json(state.runtime_draft);
        },
      ),
    );
    window.history.pushState({}, "", "/platform/runtime");
    render(<App />);

    const saveButton = await screen.findByRole("button", { name: "Save" });
    expect(saveButton).toBeDisabled();
    const model = screen.getByDisplayValue("gpt-platform");
    await user.click(screen.getByRole("button", { name: /^STTSpeech/ }));
    expect(saveButton).toBeDisabled();
    expect(screen.queryByLabelText(/JSON/i)).not.toBeInTheDocument();
    await user.clear(model);
    await user.type(model, "new-model");
    expect(await screen.findByText("Configuration warnings")).toBeVisible();
    await waitFor(() => expect(saveButton).toBeEnabled());
    expect(screen.queryByText(/Validating changes/i)).not.toBeInTheDocument();
    await user.click(saveButton);
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(await screen.findByDisplayValue("normalized-model")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Publish/ }),
    ).not.toBeInTheDocument();
  });

  it("blocks System Prompt save on Backend errors and stays quiet on valid edits", async () => {
    const user = userEvent.setup();
    let valid = false;
    const state = structuredClone(baseState);
    const save = vi.fn();
    server.use(
      http.get("/admin/v1/platform/components/state", () =>
        HttpResponse.json(state),
      ),
      http.post("/admin/v1/platform/components/system-prompt/plan", () =>
        HttpResponse.json(
          valid
            ? { valid: true, errors: [], warnings: [] }
            : {
                valid: false,
                errors: [
                  {
                    code: "prompt",
                    path: "text",
                    message: "Prompt is blocked",
                  },
                ],
                warnings: [],
              },
        ),
      ),
      http.put(
        "/admin/v1/platform/components/system-prompt/draft",
        async ({ request }) => {
          save((await request.json()) as { text: string });
          state.system_prompt_draft = {
            id: "system-draft",
            version: 1,
            value: "Normalized system prompt",
          } as never;
          return HttpResponse.json(state.system_prompt_draft);
        },
      ),
    );
    window.history.pushState({}, "", "/platform/system-prompt");
    render(<App />);
    await user.click(screen.getByRole("link", { name: "System Prompt" }));
    const editor = await screen.findByLabelText("Prompt");
    await user.type(editor, " changed");
    expect(await screen.findByText(/Prompt is blocked/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    valid = true;
    await user.type(editor, " again");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    expect(
      screen.queryByText(/Validating|Valid|No issues/),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(
      await screen.findByDisplayValue("Normalized system prompt"),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Publish/ }),
    ).not.toBeInTheDocument();
  });

  it("refreshes System Prompt after publish before allowing a new save", async () => {
    const user = userEvent.setup();
    let state: Omit<typeof baseState, "system_prompt_draft"> & {
      system_prompt_draft: {
        id: string;
        version: number;
        value: string;
      } | null;
    } = {
      ...structuredClone(baseState),
      system_prompt_draft: {
        id: "system-draft",
        version: 1,
        value: "Published with edit",
      },
    };
    const save = vi.fn();
    const publish = vi.fn();
    server.use(
      http.get("/admin/v1/platform/components/state", () =>
        HttpResponse.json(state),
      ),
      http.post("/admin/v1/platform/components/system-prompt/plan", () =>
        HttpResponse.json({ valid: true, errors: [], warnings: [] }),
      ),
      http.put(
        "/admin/v1/platform/components/system-prompt/draft",
        async ({ request }) => {
          expect(request.headers.get("If-Match")).toBeNull();
          const body = (await request.json()) as { text: string };
          save(body.text);
          state = {
            ...state,
            system_prompt_draft: {
              id: "new-system-draft",
              version: 1,
              value: body.text,
            },
          };
          return HttpResponse.json(state.system_prompt_draft);
        },
      ),
      http.post("/admin/v1/platform/components/publish", () => {
        publish();
        state = {
          ...state,
          system_prompt_draft: null,
          active_system_prompt: "System canonical after publish",
        };
        return HttpResponse.json({ id: "release", release_number: 4 });
      }),
    );
    window.history.pushState({}, "", "/platform/system-prompt");
    render(<App />);
    expect(
      await screen.findByDisplayValue("Published with edit"),
    ).toBeVisible();

    await router.navigate({ to: "/platform" as never });
    await user.click(
      await screen.findByRole("button", { name: "Publish Platform" }),
    );
    await waitFor(() => expect(publish).toHaveBeenCalledOnce());

    await router.navigate({ to: "/platform/system-prompt" as never });
    expect(
      await screen.findByDisplayValue("System canonical after publish"),
    ).toBeVisible();
    const editor = screen.getByLabelText("Prompt");
    await user.type(editor, " changed");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        "System canonical after publish changed",
      ),
    );
  });

  it("builds Profiles selector from active and draft-only keys without a default", async () => {
    let state = {
      ...baseState,
      profile_prompt_drafts: {
        draft_only: { id: "draft-profile", version: 2, value: "Draft prompt" },
      },
    };
    const save = vi.fn();
    server.use(
      http.get("/admin/v1/platform/components/state", () =>
        HttpResponse.json(state),
      ),
      http.post("/admin/v1/platform/components/profiles/:profile/plan", () =>
        HttpResponse.json({ valid: true, errors: [], warnings: [] }),
      ),
      http.put(
        "/admin/v1/platform/components/profiles/:profile/draft",
        async ({ params, request }) => {
          const body = (await request.json()) as { text: string };
          save(params.profile, body.text);
          state = {
            ...state,
            profile_prompt_drafts: {
              ...state.profile_prompt_drafts,
              [String(params.profile)]: {
                id: "saved-profile",
                version: 1,
                value: "Normalized active profile",
              },
            },
          };
          return HttpResponse.json(
            state.profile_prompt_drafts[
              String(params.profile) as keyof typeof state.profile_prompt_drafts
            ],
          );
        },
      ),
    );
    window.history.pushState({}, "", "/platform/profile-prompt");
    render(<App />);
    await userEvent
      .setup()
      .click(screen.getByRole("link", { name: "Profiles" }));
    const selector = await screen.findByLabelText("Profile");
    expect(
      within(selector)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["active_only", "draft_only"]);
    expect(
      within(selector).queryByRole("option", { name: "default" }),
    ).not.toBeInTheDocument();
    await userEvent.setup().selectOptions(selector, "draft_only");
    expect(await screen.findByDisplayValue("Draft prompt")).toBeVisible();
    expect(screen.getByText("Saved · Pending publish")).toBeVisible();
    await userEvent
      .setup()
      .selectOptions(screen.getByLabelText("Profile"), "active_only");
    const editor = await screen.findByDisplayValue("Active prompt");
    await userEvent.setup().type(editor, " changed");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("active_only", "Active prompt changed"),
    );
    expect(
      await screen.findByDisplayValue("Normalized active profile"),
    ).toBeVisible();
    await userEvent
      .setup()
      .selectOptions(screen.getByLabelText("Profile"), "draft_only");
    expect(await screen.findByDisplayValue("Draft prompt")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Publish/ }),
    ).not.toBeInTheDocument();
  });
});
