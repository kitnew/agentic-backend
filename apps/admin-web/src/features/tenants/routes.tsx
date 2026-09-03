import { IntegrationsPage } from "../integrations/page";
import {
  TenantAuthoringEditorPage,
  TenantComponentOverviewPage,
  TenantJsonComponentPage,
} from "./component-pages";
import { HandoffPage } from "./handoff-page";
import { TenantsPage } from "./pages";

export const routes = [
  { id: "tenants", path: "/tenants", component: TenantsPage },
  {
    id: "tenant-overview",
    path: "/tenants/$tenantId",
    component: TenantComponentOverviewPage,
  },
  {
    id: "tenant-runtime",
    path: "/tenants/$tenantId/runtime",
    component: () => (
      <TenantAuthoringEditorPage component="runtime" title="Runtime" />
    ),
  },
  {
    id: "tenant-speech",
    path: "/tenants/$tenantId/runtime/speech",
    component: () => (
      <TenantAuthoringEditorPage component="speech" title="Speech Overrides" />
    ),
  },
  {
    id: "tenant-profile-selection",
    path: "/tenants/$tenantId/prompt/profile-selection",
    component: () => (
      <TenantAuthoringEditorPage
        component="profile"
        title="Prompt Profile Selection"
      />
    ),
  },
  {
    id: "tenant-prompt",
    path: "/tenants/$tenantId/prompt",
    component: () => (
      <TenantAuthoringEditorPage component="prompt" title="Prompt" />
    ),
  },
  {
    id: "tenant-knowledge",
    path: "/tenants/$tenantId/knowledge-base",
    component: () => (
      <TenantAuthoringEditorPage component="knowledge" title="Knowledge Base" />
    ),
  },
  {
    id: "tenant-capabilities",
    path: "/tenants/$tenantId/capabilities",
    component: () => <TenantJsonComponentPage component="capabilities" />,
  },
  {
    id: "tenant-integrations",
    path: "/tenants/$tenantId/integrations",
    component: IntegrationsPage,
  },
  {
    id: "tenant-integration-detail",
    path: "/tenants/$tenantId/integrations/$integrationKey",
    component: IntegrationsPage,
  },
  {
    id: "tenant-post-call",
    path: "/tenants/$tenantId/post-call",
    component: () => <TenantJsonComponentPage component="post_call" />,
  },
  {
    id: "tenant-handoff",
    path: "/tenants/$tenantId/handoff",
    component: HandoffPage,
  },
];
