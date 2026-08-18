import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
	cloneElement,
	isValidElement,
	type ReactElement,
	type ReactNode,
	useId,
} from "react";
import { useForm } from "react-hook-form";

import {
	EmptyState,
	PageError,
	PageHeader,
	PageLoading,
} from "../../../components/page-states";
import { Button } from "../../../components/ui/button";
import { throwAdminResponse } from "../../../core/api/client";
import {
	createTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsPost,
	publishTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPublishPost,
	updateTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPatch,
} from "../../../core/api/generated/admin-tenant-runtime/admin-tenant-runtime";
import {
	applyPromptSetAdminV1TenantsTenantIdPromptSetApplyPost,
	createConfigDraftAdminV1TenantsTenantIdConfigDraftsPost,
	createTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsPost,
	publishConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPublishPost,
	publishTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPublishPost,
	updateConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPatch,
	updateTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPatch,
} from "../../../core/api/generated/admin-tenants/admin-tenants";
import { useTenant } from "../../../core/tenant/use-tenant";
import {
	enabledCapabilities,
	toAgentForm,
	toUpdateRequest,
} from "../lib/mappings";
import {
	agentQueryKey,
	getAgentConfiguration,
	useAgentConfiguration,
} from "../queries/agent-queries";
import { type AgentForm, agentFormSchema } from "../schemas/agent-form";

type SuccessfulResponse = { status: number; data: unknown; headers: Headers };

function responseData<T>(response: SuccessfulResponse): T {
	if (response.status >= 200 && response.status < 300)
		return response.data as T;
	return throwAdminResponse(response);
}

function changed(left: string, right: string) {
	return left !== right;
}

export function AgentPage() {
	const { tenantId } = useTenant();
	if (!tenantId)
		return <EmptyState title="Select a tenant to configure its agent" />;
	return <AgentPageContents tenantId={tenantId} />;
}

function AgentPageContents({ tenantId }: { tenantId: string }) {
	const query = useAgentConfiguration(tenantId);
	if (query.isPending) return <PageLoading />;
	if (query.isError)
		return (
			<PageError
				title={query.error.message || "Agent configuration could not be loaded"}
				onRetry={() => query.refetch()}
			/>
		);
	return (
		<AgentEditor
			key={tenantId}
			tenantId={tenantId}
			configuration={query.data}
		/>
	);
}

function AgentEditor({
	tenantId,
	configuration,
}: {
	tenantId: string;
	configuration: Awaited<ReturnType<typeof getAgentConfiguration>>;
}) {
	const queryClient = useQueryClient();
	const initial = toAgentForm(
		configuration.config,
		configuration.prompt?.text ?? "",
		configuration.runtime,
	);
	const form = useForm<AgentForm>({
		resolver: zodResolver(agentFormSchema),
		defaultValues: initial,
	});
	const save = useMutation({
		mutationFn: async (values: AgentForm) => {
			const configChanged =
				changed(values.displayName, initial.displayName) ||
				changed(values.greeting, initial.greeting) ||
				changed(values.profile, initial.profile) ||
				changed(values.defaultLocale, initial.defaultLocale);
			const promptChanged = changed(
				values.tenantInstructions,
				initial.tenantInstructions,
			);
			const runtimeChanged = changed(values.voiceId, initial.voiceId);

			if (configChanged) {
				const request = toUpdateRequest(configuration.config, values);
				const revision = configuration.configDraft
					? responseData<{ id: string }>(
							await updateConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPatch(
								tenantId,
								configuration.configDraft.id,
								request,
								{
									headers: {
										"If-Match": `"${configuration.configDraft.version}"`,
									},
								},
							),
						)
					: responseData<{ id: string }>(
							await createConfigDraftAdminV1TenantsTenantIdConfigDraftsPost(
								tenantId,
								request,
							),
						);
				responseData(
					await publishConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPublishPost(
						tenantId,
						revision.id,
					),
				);
			}

			if (promptChanged) {
				const revision =
					configuration.prompt?.status === "draft"
						? responseData<{ id: string }>(
								await updateTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPatch(
									tenantId,
									configuration.prompt.id,
									{ text: values.tenantInstructions },
									{
										headers: {
											"If-Match": `"${configuration.prompt.version}"`,
										},
									},
								),
							)
						: responseData<{ id: string }>(
								await createTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsPost(
									tenantId,
									{ text: values.tenantInstructions },
								),
							);
				responseData(
					await publishTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPublishPost(
						tenantId,
						revision.id,
					),
				);
			}

			if (runtimeChanged) {
				const request = {
					settings: values.voiceId ? { tts: { voice_id: values.voiceId } } : {},
				};
				const draft = configuration.runtime.draft_revision;
				const revision = draft
					? responseData<{ id: string }>(
							await updateTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPatch(
								tenantId,
								draft.id,
								request,
								{ headers: { "If-Match": `"${draft.version}"` } },
							),
						)
					: responseData<{ id: string }>(
							await createTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsPost(
								tenantId,
								request,
							),
						);
				responseData(
					await publishTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPublishPost(
						tenantId,
						revision.id,
					),
				);
			}

			if (configChanged || promptChanged)
				responseData(
					await applyPromptSetAdminV1TenantsTenantIdPromptSetApplyPost(
						tenantId,
					),
				);

			const canonical = await getAgentConfiguration(tenantId);
			queryClient.setQueryData(agentQueryKey(tenantId), canonical);
			return canonical;
		},
		onSuccess: (canonical) =>
			form.reset(
				toAgentForm(
					canonical.config,
					canonical.prompt?.text ?? "",
					canonical.runtime,
				),
			),
	});
	const capabilities = enabledCapabilities(configuration.config);

	return (
		<>
			<PageHeader
				title="Agent"
				detail="Configure the tenant-specific agent behavior. Changes publish new control-plane revisions."
			/>
			<form
				className="max-w-3xl space-y-8"
				onSubmit={form.handleSubmit((values) => save.mutate(values))}
			>
				<div className="flex items-center justify-between gap-3 border-b pb-4">
					<p aria-live="polite" className="text-sm text-muted">
						{save.isPending
							? "Saving changes…"
							: save.isSuccess
								? "Agent configuration saved"
								: form.formState.isDirty
									? "Unsaved changes"
									: "All changes saved"}
					</p>
					<div className="flex gap-2">
						<Button
							disabled={!form.formState.isDirty || save.isPending}
							onClick={() => form.reset(initial)}
							variant="outline"
						>
							Reset
						</Button>
						<Button
							disabled={!form.formState.isDirty || save.isPending}
							type="submit"
						>
							Save changes
						</Button>
					</div>
				</div>
				{save.isError && (
					<PageError
						compact
						title={save.error.message || "Failed to save agent configuration"}
					/>
				)}

				<section aria-labelledby="general-heading" className="space-y-4">
					<h2 className="text-lg font-semibold" id="general-heading">
						General
					</h2>
					<Field
						label="Agent name"
						error={form.formState.errors.displayName?.message}
					>
						<input {...form.register("displayName")} />
					</Field>
					<Field
						label="Greeting"
						error={form.formState.errors.greeting?.message}
					>
						<textarea {...form.register("greeting")} rows={3} />
					</Field>
					<Field label="Profile" error={form.formState.errors.profile?.message}>
						<select {...form.register("profile")}>
							{configuration.profiles.map((profile) => (
								<option key={profile} value={profile}>
									{profile.replaceAll("_", " ")}
								</option>
							))}
						</select>
					</Field>
					<Field
						label="Default locale"
						error={form.formState.errors.defaultLocale?.message}
					>
						<input {...form.register("defaultLocale")} />
					</Field>
				</section>

				<section
					aria-labelledby="prompts-heading"
					className="space-y-4 border-t pt-6"
				>
					<h2 className="text-lg font-semibold" id="prompts-heading">
						Prompts
					</h2>
					<PromptViewer
						label="Platform system prompt"
						detail="Managed by platform"
						text={configuration.systemPrompt}
					/>
					<PromptViewer
						label={`Profile prompt: ${configuration.config.agent.profile.replaceAll("_", " ")}`}
						detail="Managed by profile"
						text={configuration.profilePrompt}
					/>
					<Field
						label="Tenant instructions"
						error={form.formState.errors.tenantInstructions?.message}
						detail="Editable for this tenant."
					>
						<textarea {...form.register("tenantInstructions")} rows={10} />
					</Field>
				</section>

				<section
					aria-labelledby="runtime-heading"
					className="space-y-4 border-t pt-6"
				>
					<h2 className="text-lg font-semibold" id="runtime-heading">
						Runtime
					</h2>
					<Field
						label="TTS voice ID"
						detail="The only tenant runtime override currently supported by the Admin API."
						error={form.formState.errors.voiceId?.message}
					>
						<input {...form.register("voiceId")} />
					</Field>
				</section>

				<section
					aria-labelledby="capabilities-heading"
					className="space-y-2 border-t pt-6"
				>
					<h2 className="text-lg font-semibold" id="capabilities-heading">
						Capabilities
					</h2>
					{capabilities.length ? (
						<ul className="list-inside list-disc text-sm">
							{capabilities.map((capability) => (
								<li key={capability}>{capability}</li>
							))}
						</ul>
					) : (
						<p className="text-sm text-muted">No enabled capabilities.</p>
					)}
				</section>
			</form>
		</>
	);
}

function Field({
	label,
	detail,
	error,
	children,
}: {
	label: string;
	detail?: string;
	error?: string;
	children: ReactNode;
}) {
	const id = useId();
	const errorId = `${id}-error`;
	return (
		<label className="block space-y-1" htmlFor={id}>
			<span className="font-medium">{label}</span>
			{detail && <span className="block text-sm text-muted">{detail}</span>}
			{isValidElement(children)
				? cloneElement(
						children as ReactElement<{
							id?: string;
							"aria-describedby"?: string;
						}>,
						{
							id,
							"aria-describedby": error ? errorId : undefined,
						},
					)
				: children}
			{error && (
				<span className="block text-sm text-red-700" id={errorId} role="alert">
					{error}
				</span>
			)}
		</label>
	);
}

function PromptViewer({
	label,
	detail,
	text,
}: {
	label: string;
	detail: string;
	text?: string;
}) {
	return (
		<details className="rounded-md border p-3">
			<summary className="cursor-pointer font-medium">{label}</summary>
			<p className="mt-1 text-sm text-muted">{detail}</p>
			<pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-sm">
				{text ?? "No published prompt content is available."}
			</pre>
		</details>
	);
}
