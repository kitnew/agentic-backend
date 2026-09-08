import { Link } from "@tanstack/react-router";

import { EmptyState, PageHeader } from "../../components/page-states";
import { TenantConfigurationEditor } from "../../core/configuration/high-level";
import { useTenant } from "../../core/tenant/use-tenant";

const sections = [
  ["Runtime", "runtime"],
  ["Speech Overrides", "runtime/speech"],
  ["Prompt Profile Selection", "prompt/profile-selection"],
  ["Tenant Prompt", "prompt"],
  ["Knowledge", "knowledge-base"],
  ["Capabilities", "capabilities"],
  ["Post-call", "post-call"],
] as const;

export function TenantComponentOverviewPage() {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  return (
    <>
      <PageHeader
        title="Tenant"
        detail="Tenant configuration is managed as one validated Control Plane aggregate."
      />
      <div className="grid gap-3 md:grid-cols-2">
        {sections.map(([title, path]) => (
          <Link
            className="rounded border p-4"
            key={path}
            to={`/tenants/${tenantId}/${path}` as never}
          >
            {title}
          </Link>
        ))}
      </div>
    </>
  );
}

function Editor() {
  const { tenantId } = useTenant();
  return tenantId ? (
    <TenantConfigurationEditor tenantId={tenantId} />
  ) : (
    <EmptyState title="Select a tenant" />
  );
}

export function TenantAuthoringEditorPage(_props: {
  component: "runtime" | "speech" | "profile" | "prompt" | "knowledge";
  title: string;
}) {
  return <Editor />;
}

export function TenantJsonComponentPage(_props: {
  component: "capabilities" | "post_call";
}) {
  return <Editor />;
}
