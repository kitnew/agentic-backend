import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../src/app/providers";
import { queryClient } from "../src/app/query-client";
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

const openaiConnection = {
  ...connection,
  key: "openai-main",
  provider_kind: "openai",
  connection_config: {},
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
          metadata: {
            service_tiers: { default: "Standard", priority: "Fast" },
          },
        },
        {
          key: "openai",
          name: "OpenAI",
          description: "OpenAI API provider",
          metadata: {
            service_tiers: { default: "Standard", fast: "Fast" },
          },
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

    await user.type(screen.getByLabelText("Connection key"), "openai-main");
    await user.selectOptions(screen.getByLabelText("Provider kind"), "openai");
    await user.selectOptions(screen.getByLabelText("Credential"), credentialId);
    expect(
      screen.queryByLabelText("Connection config"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create connection" }));

    await waitFor(() => expect(connectionRequest).toBeDefined());
    const createdConnectionRequest = requiredRequest(connectionRequest);
    expect(await createdConnectionRequest.clone().json()).toEqual({
      key: "openai-main",
      provider_kind: "openai",
      credential_ref: credentialId,
      connection_config: {},
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

  it("creates OpenAI deployments from typed model, service tier, and capabilities", async () => {
    const user = userEvent.setup();
    let deploymentRequest: Request | undefined;
    queryClient.setQueryData(["control-plane", "model-deployments"], []);
    server.use(
      http.get("/management/v1/credentials", () =>
        HttpResponse.json([credential]),
      ),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([openaiConnection]),
      ),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([
          {
            key: "openai",
            name: "OpenAI",
            description: "OpenAI API provider",
            metadata: {
              service_tiers: { default: "Standard", fast: "Fast" },
            },
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
    await user.selectOptions(
      await screen.findByLabelText("Service tier"),
      "fast",
    );
    await user.type(screen.getByLabelText("Model"), "gpt");
    await user.click(screen.getByLabelText("Supports temperature"));
    await user.click(screen.getByRole("button", { name: "Create deployment" }));

    await waitFor(() => expect(deploymentRequest).toBeDefined());
    const createdDeploymentRequest = requiredRequest(deploymentRequest);
    expect(await createdDeploymentRequest.clone().json()).toEqual({
      key: "llm-main",
      connection_ref: connectionId,
      deployment_kind: "llm",
      deployment_config: { model: "gpt", service_tier: "fast" },
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
    await waitFor(() =>
      expect(
        queryClient.getQueryState(["control-plane", "model-deployments"])
          ?.isInvalidated,
      ).toBe(true),
    );
  });

  it("creates a Soniox cascade STT deployment from its focused form", async () => {
    const user = userEvent.setup();
    let deploymentRequest: Request | undefined;
    const sonioxConnection = { ...openaiConnection, provider_kind: "soniox" };
    server.use(
      http.get("/management/v1/credentials", () =>
        HttpResponse.json([credential]),
      ),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([sonioxConnection]),
      ),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([]),
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([
          {
            key: "soniox",
            name: "Soniox",
            description: "Soniox STT",
            metadata: { deployment_kinds: ["stt"] },
          },
        ]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([
          {
            key: "stt",
            name: "STT",
            description: "STT deployment",
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

    expect(
      await screen.findByRole("option", { name: "Soniox (soniox)" }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Deployment key"), "soniox-sk");
    await user.selectOptions(screen.getByLabelText("Connection"), connectionId);
    await user.selectOptions(screen.getByLabelText("Deployment kind"), "stt");
    expect(screen.getByLabelText("Soniox model")).toHaveValue("stt-rt-v5");
    expect(
      screen.queryByLabelText("Deployment config"),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Capabilities")).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText("Soniox maximum endpoint delay"));
    await user.type(
      screen.getByLabelText("Soniox maximum endpoint delay"),
      "700",
    );
    await user.click(screen.getByRole("button", { name: "Create deployment" }));

    await waitFor(() => expect(deploymentRequest).toBeDefined());
    expect(
      await requiredRequest(deploymentRequest).clone().json(),
    ).toMatchObject({
      key: "soniox-sk",
      connection_ref: connectionId,
      deployment_kind: "stt",
      deployment_config: {
        model: "stt-rt-v5",
        max_endpoint_delay_ms: 700,
        endpoint_sensitivity: null,
        endpoint_latency_adjustment_level: null,
      },
      capabilities: {
        kind: "stt",
        supports_cascade: true,
        supports_realtime_input_transcription: false,
      },
    });
  });

  it("creates a Soniox EU connection with its credential", async () => {
    const user = userEvent.setup();
    let connectionRequest: Request | undefined;
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
            key: "soniox",
            name: "Soniox",
            description: "Soniox STT",
            metadata: {},
          },
        ]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([]),
      ),
      http.post("/management/v1/providers/connections", async ({ request }) => {
        connectionRequest = request;
        return HttpResponse.json(connection, { status: 201 });
      }),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    await user.type(
      await screen.findByLabelText("Connection key"),
      "soniox-main",
    );
    await user.selectOptions(screen.getByLabelText("Provider kind"), "soniox");
    await user.selectOptions(screen.getByLabelText("Credential"), credentialId);
    expect(
      screen.queryByLabelText("Connection config"),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Soniox processing region")).toHaveValue("eu");
    await user.click(screen.getByRole("button", { name: "Create connection" }));

    await waitFor(() => expect(connectionRequest).toBeDefined());
    expect(await requiredRequest(connectionRequest).clone().json()).toEqual({
      key: "soniox-main",
      provider_kind: "soniox",
      credential_ref: credentialId,
      connection_config: { region: "eu" },
    });
  });

  it("edits an existing Soniox deployment with its current ETag", async () => {
    const user = userEvent.setup();
    let updateRequest: Request | undefined;
    const sonioxConnection = { ...openaiConnection, provider_kind: "soniox" };
    const sonioxDeployment = {
      ...deployment,
      key: "soniox-sk",
      connection_ref: connectionId,
      deployment_kind: "stt",
      deployment_config: { model: "stt-rt-v5", max_endpoint_delay_ms: 2000 },
      capabilities: {
        kind: "stt",
        supports_cascade: true,
        supports_realtime_input_transcription: false,
      },
    };
    server.use(
      http.get("/management/v1/credentials", () =>
        HttpResponse.json([credential]),
      ),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([sonioxConnection]),
      ),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([sonioxDeployment]),
      ),
      http.get("/management/v1/providers/deployments/:id", () =>
        HttpResponse.json(sonioxDeployment, {
          headers: { ETag: '"soniox-v1"' },
        }),
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([
          {
            key: "soniox",
            name: "Soniox",
            description: "Soniox STT",
            metadata: {},
          },
        ]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([
          {
            key: "stt",
            name: "STT",
            description: "STT deployment",
            metadata: {},
          },
        ]),
      ),
      http.put(
        "/management/v1/providers/deployments/:id",
        async ({ request }) => {
          updateRequest = request;
          return HttpResponse.json(sonioxDeployment);
        },
      ),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    const editButtons = await screen.findAllByRole("button", { name: "Edit" });
    await user.click(editButtons[1]);
    expect(screen.getByLabelText("Soniox maximum endpoint delay")).toHaveValue(
      2000,
    );
    await user.clear(screen.getByLabelText("Soniox maximum endpoint delay"));
    await user.type(
      screen.getByLabelText("Soniox maximum endpoint delay"),
      "700",
    );
    await user.click(screen.getByRole("button", { name: "Save deployment" }));

    await waitFor(() => expect(updateRequest).toBeDefined());
    const request = requiredRequest(updateRequest);
    expect(request.headers.get("If-Match")).toBe('"soniox-v1"');
    expect(await request.clone().json()).toMatchObject({
      connection_ref: connectionId,
      deployment_config: { model: "stt-rt-v5", max_endpoint_delay_ms: 700 },
      capabilities: sonioxDeployment.capabilities,
    });
  });

  it("updates the service tier of an existing deployment from the list", async () => {
    const user = userEvent.setup();
    let updateRequest: Request | undefined;
    const existingDeployment = {
      ...deployment,
      connection_ref: openaiConnection.id,
      deployment_config: { model: "gpt", service_tier: "default" },
    };
    server.use(
      http.get("/management/v1/credentials", () =>
        HttpResponse.json([credential]),
      ),
      http.get("/management/v1/providers/connections", () =>
        HttpResponse.json([openaiConnection]),
      ),
      http.get("/management/v1/providers/deployments", () =>
        HttpResponse.json([existingDeployment]),
      ),
      http.get("/management/v1/providers/deployments/:id", () =>
        HttpResponse.json(existingDeployment, {
          headers: { ETag: '"deployment-v1"' },
        }),
      ),
      http.put(
        "/management/v1/providers/deployments/:id",
        async ({ request }) => {
          updateRequest = request;
          return HttpResponse.json({
            ...existingDeployment,
            deployment_config: { model: "gpt", service_tier: "fast" },
          });
        },
      ),
      http.get("/management/v1/registries/provider-kinds", () =>
        HttpResponse.json([
          {
            key: "openai",
            name: "OpenAI",
            description: "OpenAI API provider",
            metadata: {
              service_tiers: { default: "Standard", fast: "Fast" },
            },
          },
        ]),
      ),
      http.get("/management/v1/registries/deployment-kinds", () =>
        HttpResponse.json([]),
      ),
    );
    window.history.pushState({}, "", "/platform/providers");
    renderProviders();

    const tierSelect = await screen.findByLabelText("Service tier llm-main");
    expect(tierSelect).toHaveValue("default");
    await user.selectOptions(tierSelect, "fast");

    await waitFor(() => expect(updateRequest).toBeDefined());
    const request = requiredRequest(updateRequest);
    expect(await request.clone().json()).toEqual({
      connection_ref: openaiConnection.id,
      deployment_config: { model: "gpt", service_tier: "fast" },
      capabilities: deployment.capabilities,
    });
    expect(request.headers.get("If-Match")).toBe('"deployment-v1"');
  });

  it("creates Azure connections from endpoint and optional API version fields", async () => {
    const user = userEvent.setup();
    let connectionRequest: Request | undefined;
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
            key: "openai",
            name: "OpenAI",
            description: "OpenAI API provider",
            metadata: {},
          },
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
      http.post("/management/v1/providers/connections", async ({ request }) => {
        connectionRequest = request;
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
    await user.type(
      screen.getByLabelText("Azure OpenAI endpoint"),
      "https://azure.example.test",
    );
    await user.type(screen.getByLabelText("API version"), "2026-01-01");
    await user.click(screen.getByRole("button", { name: "Create connection" }));

    await waitFor(() => expect(connectionRequest).toBeDefined());
    expect(
      await requiredRequest(connectionRequest).clone().json(),
    ).toMatchObject({
      provider_kind: "azure_openai",
      connection_config: {
        endpoint: "https://azure.example.test",
        api_version: "2026-01-01",
      },
    });
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
