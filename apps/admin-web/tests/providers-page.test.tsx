import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../src/app/providers";
import { PlatformProvidersPage } from "../src/features/platform/providers-page";
import { server } from "./setup";

const credentialId = "11111111-1111-4111-8111-111111111111";
const connectionId = "22222222-2222-4222-8222-222222222222";
const deploymentId = "33333333-3333-4333-8333-333333333333";

const credential = {
  id: credentialId,
  name: "Azure platform",
  scope: { type: "platform" },
  status: "active",
  active_secret_version: 1,
  revoked_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const connection = {
  id: connectionId,
  key: "azure-main",
  provider_kind: "azure_openai",
  credential_ref: credentialId,
  connection_config: { endpoint: "https://example.test" },
  enabled: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const deployment = {
  id: deploymentId,
  key: "llm-main",
  connection_ref: connectionId,
  deployment_kind: "llm",
  deployment_config: { model: "gpt" },
  capabilities: {
    kind: "llm",
    supports_temperature: true,
    supports_reasoning_effort: false,
  },
  enabled: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function emptyProviderHandlers() {
  return [
    http.get("/management/v1/credentials", () => HttpResponse.json([])),
    http.get("/management/v1/providers/connections", () =>
      HttpResponse.json([]),
    ),
    http.get("/management/v1/providers/deployments", () =>
      HttpResponse.json([]),
    ),
    http.get("/management/v1/registries/provider-kinds", () =>
      HttpResponse.json([
        {
          key: "azure_openai",
          name: "Azure OpenAI",
          description: "Azure provider",
          metadata: {},
        },
      ]),
    ),
    http.get("/management/v1/registries/deployment-kinds", () =>
      HttpResponse.json([
        {
          key: "llm",
          name: "Large language model",
          description: "LLM deployment",
          metadata: {},
        },
      ]),
    ),
  ];
}

function renderProviders() {
  return render(
    <AppProviders>
      <PlatformProvidersPage />
    </AppProviders>,
  );
}

function requiredRequest(request: Request | undefined): Request {
  if (!request) throw new Error("Expected request was not captured");
  return request;
}

describe("Admin Web Slice B provider provisioning", () => {
  it("uses registry choices and exact credential/connection create contracts", async () => {
    const user = userEvent.setup();
    let credentials = [] as (typeof credential)[];
    let connectionRequest: Request | undefined;
    let credentialRequest: Request | undefined;
    server.use(
      ...emptyProviderHandlers().map((handler, index) =>
        index === 0
          ? http.get("/management/v1/credentials", () =>
              HttpResponse.json(credentials),
            )
          : handler,
      ),
      http.post("/management/v1/credentials", async ({ request }) => {
        credentialRequest = request;
        credentials = [credential];
        return HttpResponse.json(credential, { status: 201 });
      }),
      http.post("/management/v1/providers/connections", async ({ request }) => {
        connectionRequest = request;
        return HttpResponse.json(connection, { status: 201 });
      }),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    await user.type(
      await screen.findByLabelText("Credential name"),
      "Azure platform",
    );
    await user.type(screen.getByLabelText("Secret"), "top-secret");
    await user.click(screen.getByRole("button", { name: "Create credential" }));

    await waitFor(() => expect(credentialRequest).toBeDefined());
    const createdCredentialRequest = requiredRequest(credentialRequest);
    expect(await createdCredentialRequest.clone().json()).toEqual({
      scope: { type: "platform" },
      name: "Azure platform",
      secret: "top-secret",
    });
    expect(createdCredentialRequest.headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f-]{36}$/,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Secret")).toHaveValue(""),
    );
    expect(screen.queryByText("top-secret")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Connection key"), "azure-main");
    await user.selectOptions(
      screen.getByLabelText("Provider kind"),
      "azure_openai",
    );
    await user.selectOptions(screen.getByLabelText("Credential"), credentialId);
    await user.clear(screen.getByLabelText("Connection config"));
    fireEvent.change(screen.getByLabelText("Connection config"), {
      target: {
        value: '{"endpoint":"https://example.test","region":"west"}',
      },
    });
    await user.click(screen.getByRole("button", { name: "Create connection" }));

    await waitFor(() => expect(connectionRequest).toBeDefined());
    const createdConnectionRequest = requiredRequest(connectionRequest);
    expect(await createdConnectionRequest.clone().json()).toEqual({
      key: "azure-main",
      provider_kind: "azure_openai",
      credential_ref: credentialId,
      connection_config: {
        endpoint: "https://example.test",
        region: "west",
      },
    });
    expect(Object.keys(await createdConnectionRequest.clone().json())).toEqual([
      "key",
      "provider_kind",
      "credential_ref",
      "connection_config",
    ]);
    expect(createdConnectionRequest.headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f-]{36}$/,
    );
  });

  it("renders registry errors without local fallback choices", async () => {
    server.use(
      ...emptyProviderHandlers().filter((_, index) => index !== 3),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json(
          {
            code: "registry_unavailable",
            message: "Provider registry unavailable",
            issues: [],
            request_id: "request-registry",
          },
          { status: 503 },
        ),
      ),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    expect(
      await screen.findByText("Provider registry unavailable"),
    ).toBeVisible();
    expect(screen.getByText("Code: registry_unavailable")).toBeVisible();
    expect(screen.getByText("Request ID: request-registry")).toBeVisible();
    expect(
      screen.queryByRole("option", { name: /openai/i }),
    ).not.toBeInTheDocument();
  });

  it("creates deployments with registry kind, selected connection ID, and preserved JSON", async () => {
    const user = userEvent.setup();
    let deploymentRequest: Request | undefined;
    server.use(
      http.get("/management/v1/credentials", () =>
        HttpResponse.json([credential]),
      ),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([connection]),
      ),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([
          {
            key: "llm",
            name: "Large language model",
            description: "LLM deployment",
            metadata: {},
          },
        ]),
      ),
      http.post("/management/v1/providers/deployments", async ({ request }) => {
        deploymentRequest = request;
        return HttpResponse.json(deployment, { status: 201 });
      }),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    await user.type(await screen.findByLabelText("Deployment key"), "llm-main");
    await user.selectOptions(
      await screen.findByLabelText("Connection"),
      connectionId,
    );
    await user.selectOptions(screen.getByLabelText("Deployment kind"), "llm");
    await user.clear(screen.getByLabelText("Deployment config"));
    fireEvent.change(screen.getByLabelText("Deployment config"), {
      target: { value: '{"model":"gpt"}' },
    });
    await user.clear(screen.getByLabelText("Capabilities"));
    fireEvent.change(screen.getByLabelText("Capabilities"), {
      target: {
        value:
          '{"kind":"llm","supports_temperature":true,"supports_reasoning_effort":false}',
      },
    });
    await user.click(screen.getByRole("button", { name: "Create deployment" }));

    await waitFor(() => expect(deploymentRequest).toBeDefined());
    const createdDeploymentRequest = requiredRequest(deploymentRequest);
    expect(await createdDeploymentRequest.clone().json()).toEqual({
      key: "llm-main",
      connection_ref: connectionId,
      deployment_kind: "llm",
      deployment_config: { model: "gpt" },
      capabilities: {
        kind: "llm",
        supports_temperature: true,
        supports_reasoning_effort: false,
      },
    });
    expect(Object.keys(await createdDeploymentRequest.clone().json())).toEqual([
      "key",
      "connection_ref",
      "deployment_kind",
      "deployment_config",
      "capabilities",
    ]);
    expect(createdDeploymentRequest.headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f-]{36}$/,
    );
  });

  it("rejects malformed JSON locally and does not send a connection request", async () => {
    const user = userEvent.setup();
    const post = vi.fn();
    server.use(
      http.get("/management/v1/credentials", () =>
        HttpResponse.json([credential]),
      ),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([
          {
            key: "azure_openai",
            name: "Azure OpenAI",
            description: "Azure provider",
            metadata: {},
          },
        ]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([]),
      ),
      http.post("/management/v1/providers/connections", () => {
        post();
        return HttpResponse.json(connection, { status: 201 });
      }),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    await user.type(await screen.findByLabelText("Connection key"), "broken");
    await user.selectOptions(
      await screen.findByLabelText("Provider kind"),
      "azure_openai",
    );
    await user.selectOptions(
      await screen.findByLabelText("Credential"),
      credentialId,
    );
    await user.clear(screen.getByLabelText("Connection config"));
    fireEvent.change(screen.getByLabelText("Connection config"), {
      target: { value: "{broken" },
    });
    await user.click(screen.getByRole("button", { name: "Create connection" }));

    expect(
      await screen.findByText("Connection config must be valid JSON."),
    ).toBeVisible();
    expect(post).not.toHaveBeenCalled();
  });

  it("enables a disabled connection with its current ETag and refetches state", async () => {
    const user = userEvent.setup();
    let enabled = false;
    let enableRequest: Request | undefined;
    let listCalls = 0;
    server.use(
      http.get("/management/v1/credentials", () => HttpResponse.json([])),
      http.get("/management/v1/providers/connections", () => {
        listCalls += 1;
        return HttpResponse.json([{ ...connection, enabled }]);
      }),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([]),
      ),
      http.get(`/management/v1/providers/connections/${connectionId}`, () =>
        HttpResponse.json(connection, {
          headers: { ETag: '"connection-etag"' },
        }),
      ),
      http.post(
        `/management/v1/providers/connections/${connectionId}/enable`,
        async ({ request }) => {
          enableRequest = request;
          enabled = true;
          return HttpResponse.json({ ...connection, enabled: true });
        },
      ),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    await user.click(await screen.findByRole("button", { name: "Enable" }));
    await waitFor(() => expect(enableRequest).toBeDefined());
    const connectionEnableRequest = requiredRequest(enableRequest);
    expect(connectionEnableRequest.headers.get("If-Match")).toBe(
      '"connection-etag"',
    );
    expect(connectionEnableRequest.headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f-]{36}$/,
    );
    await waitFor(() => expect(screen.getByText("Enabled")).toBeVisible());
    expect(listCalls).toBeGreaterThan(1);
  });

  it("renders structured 422 and 412 errors for resource mutations", async () => {
    const user = userEvent.setup();
    server.use(
      ...emptyProviderHandlers(),
      http.post("/management/v1/credentials", () =>
        HttpResponse.json(
          {
            code: "credential_conflict",
            message: "Credential name already exists",
            issues: [
              {
                path: "name",
                code: "already_exists",
                message: "Choose another name",
              },
            ],
            request_id: "request-422",
          },
          { status: 422 },
        ),
      ),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();
    await user.type(
      await screen.findByLabelText("Credential name"),
      "Duplicate",
    );
    await user.type(screen.getByLabelText("Secret"), "secret");
    await user.click(screen.getByRole("button", { name: "Create credential" }));
    expect(
      await screen.findByText("Credential name already exists"),
    ).toBeVisible();
    expect(screen.getByText("Code: credential_conflict")).toBeVisible();
    expect(
      screen.getByText("name: already_exists: Choose another name"),
    ).toBeVisible();
    expect(screen.getByText("Request ID: request-422")).toBeVisible();
  });

  it("enables a disabled deployment with its current ETag and refetches state", async () => {
    const user = userEvent.setup();
    let enabled = false;
    let enableRequest: Request | undefined;
    let listCalls = 0;
    server.use(
      http.get("/management/v1/credentials", () => HttpResponse.json([])),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/providers/deployments", () => {
        listCalls += 1;
        return HttpResponse.json([{ ...deployment, enabled }]);
      }),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([]),
      ),
      http.get(`/management/v1/providers/deployments/${deploymentId}`, () =>
        HttpResponse.json(deployment, {
          headers: { ETag: '"deployment-etag"' },
        }),
      ),
      http.post(
        `/management/v1/providers/deployments/${deploymentId}/enable`,
        async ({ request }) => {
          enableRequest = request;
          enabled = true;
          return HttpResponse.json({ ...deployment, enabled: true });
        },
      ),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    await user.click(await screen.findByRole("button", { name: "Enable" }));
    await waitFor(() => expect(enableRequest).toBeDefined());
    const deploymentEnableRequest = requiredRequest(enableRequest);
    expect(deploymentEnableRequest.headers.get("If-Match")).toBe(
      '"deployment-etag"',
    );
    expect(deploymentEnableRequest.headers.get("Idempotency-Key")).toMatch(
      /^[0-9a-f-]{36}$/,
    );
    await waitFor(() => expect(screen.getByText("Enabled")).toBeVisible());
    expect(listCalls).toBeGreaterThan(1);
  });

  it("keeps a stale ETag failure distinguishable as a concurrency error", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/management/v1/credentials", () => HttpResponse.json([])),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([{ ...connection, enabled: false }]),
      ),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([]),
      ),
      http.get(`/management/v1/providers/connections/${connectionId}`, () =>
        HttpResponse.json(connection, { headers: { ETag: '"stale-etag"' } }),
      ),
      http.post(
        `/management/v1/providers/connections/${connectionId}/enable`,
        () =>
          HttpResponse.json(
            {
              code: "stale_etag",
              message: "The connection changed on the server",
              issues: [],
              request_id: "request-412",
            },
            { status: 412 },
          ),
      ),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();
    await user.click(await screen.findByRole("button", { name: "Enable" }));
    expect(
      await screen.findByText("The connection changed on the server"),
    ).toBeVisible();
    expect(screen.getByText("Code: stale_etag")).toBeVisible();
    expect(screen.getByText("Request ID: request-412")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
  });
});
