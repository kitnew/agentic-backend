import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import { server } from "./setup";

const tenantId = "11111111-1111-4111-8111-111111111111";
let agentName = "Amelia";

const tenant = {
	id: tenantId,
	slug: "debug-hotel",
	display_name: "Debug Hotel",
	business_type: "hotel",
	status: "active",
	active_config_revision_id: "config-published",
	active_prompt_set_revision_id: "prompt-set",
	active_voice_runtime_revision_id: null,
	created_at: "2026-01-01T00:00:00Z",
	updated_at: "2026-01-01T00:00:00Z",
};

function config() {
	return {
		schema_version: 4,
		agent: {
			display_name: agentName,
			greeting: "Hello",
			profile: "hotel_assistant",
		},
		business: { name: "Debug Hotel", type: "hotel" },
		conversation: { scope: "property_only" },
		localization: { default_locale: "sk-SK", timezone: "Europe/Bratislava" },
		capabilities: { "reservation.check_availability": { enabled: true } },
	};
}

function handlers() {
	return [
		http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
		http.get(`/admin/v1/tenants/${tenantId}/config/active`, () =>
			HttpResponse.json({
				tenant_id: tenantId,
				revision_id: "config-published",
				revision_number: 1,
				published_at: "2026-01-01T00:00:00Z",
				config: config(),
			}),
		),
		http.get(`/admin/v1/tenants/${tenantId}/config/revisions`, () =>
			HttpResponse.json([]),
		),
		http.get(`/admin/v1/tenants/${tenantId}/tenant-prompt/revisions`, () =>
			HttpResponse.json([
				{
					id: "tenant-prompt",
					prompt_id: "prompt",
					tenant_id: tenantId,
					text: "Be helpful.",
					status: "published",
					version: 1,
					revision_number: 1,
					created_at: "2026-01-01T00:00:00Z",
					published_at: "2026-01-01T00:00:00Z",
				},
			]),
		),
		http.get(`/admin/v1/tenants/${tenantId}/runtime`, () =>
			HttpResponse.json({
				draft_revision: null,
				latest_published_revision: null,
			}),
		),
		http.get("/admin/v1/platform/prompts/profiles", () =>
			HttpResponse.json(["hotel_assistant"]),
		),
		http.get("/admin/v1/platform/prompts/system/default/revisions", () =>
			HttpResponse.json([
				{ id: "system", text: "System", status: "published" },
			]),
		),
		http.get(
			"/admin/v1/platform/prompts/profiles/hotel_assistant/revisions",
			() =>
				HttpResponse.json([
					{ id: "profile", text: "Profile", status: "published" },
				]),
		),
	];
}

function renderAgent() {
	window.history.pushState({}, "", `/tenants/${tenantId}/agent`);
	server.use(...handlers());
	return render(<App />);
}

afterEach(() => {
	agentName = "Amelia";
});

describe("Agent page", () => {
	it("loads, becomes dirty, resets, validates, and exposes read-only prompt layers", async () => {
		const user = userEvent.setup();
		renderAgent();
		expect(await screen.findByDisplayValue("Amelia")).toBeVisible();
		await user.click(screen.getByText("Platform system prompt"));
		expect(screen.getByText("System")).toBeVisible();
		const name = screen.getByLabelText("Agent name");
		await user.clear(name);
		await user.click(screen.getByRole("button", { name: "Save changes" }));
		expect(await screen.findByText("Agent name is required")).toBeVisible();
		await user.type(name, "Edited");
		expect(screen.getByText("Unsaved changes")).toBeVisible();
		await user.click(screen.getByRole("button", { name: "Reset" }));
		expect(screen.getByDisplayValue("Amelia")).toBeVisible();
	});

	it("publishes a changed configuration and reloads canonical data", async () => {
		const user = userEvent.setup();
		const save = vi.fn();
		server.use(
			...handlers(),
			http.post(
				`/admin/v1/tenants/${tenantId}/config/drafts`,
				async ({ request }) => {
					const body = (await request.json()) as {
						config: { agent: { display_name: string } };
					};
					agentName = body.config.agent.display_name;
					save();
					return HttpResponse.json({ id: "config-draft" }, { status: 201 });
				},
			),
			http.post(
				`/admin/v1/tenants/${tenantId}/config/drafts/config-draft/publish`,
				() => HttpResponse.json({ id: "config-draft" }),
			),
			http.post(`/admin/v1/tenants/${tenantId}/prompt-set/apply`, () =>
				HttpResponse.json({ changed: true, prompt_set: {} }),
			),
		);
		window.history.pushState({}, "", `/tenants/${tenantId}/agent`);
		render(<App />);
		const name = await screen.findByLabelText("Agent name");
		await user.clear(name);
		await user.type(name, "Amelia Updated");
		await user.click(screen.getByRole("button", { name: "Save changes" }));
		expect(await screen.findByText("Agent configuration saved")).toBeVisible();
		expect(save).toHaveBeenCalledOnce();
		expect(screen.getByDisplayValue("Amelia Updated")).toBeVisible();
	});

	it("renders a backend save failure", async () => {
		const user = userEvent.setup();
		server.use(
			...handlers(),
			http.post(`/admin/v1/tenants/${tenantId}/config/drafts`, () =>
				HttpResponse.json(
					{ detail: "profile is unavailable" },
					{ status: 422 },
				),
			),
		);
		window.history.pushState({}, "", `/tenants/${tenantId}/agent`);
		render(<App />);
		const name = await screen.findByLabelText("Agent name");
		await user.clear(name);
		await user.type(name, "Blocked");
		await user.click(screen.getByRole("button", { name: "Save changes" }));
		expect(await screen.findByText("profile is unavailable")).toBeVisible();
	});
});
