import { DeferredFeaturePage } from "../deferred/deferred-feature-page";
import {
  TenantAuthoringEditorPage,
  TenantComponentOverviewPage,
} from "./component-pages";
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
    component: () => <DeferredFeaturePage title="Capabilities" />,
  },
  {
    id: "tenant-integrations",
    path: "/tenants/$tenantId/integrations",
    component: () => <DeferredFeaturePage title="Integrations" />,
  },
  {
    id: "tenant-integration-detail",
    path: "/tenants/$tenantId/integrations/$integrationKey",
    component: () => <DeferredFeaturePage title="Integrations" />,
  },
  {
    id: "tenant-post-call",
    path: "/tenants/$tenantId/post-call",
    component: () => <DeferredFeaturePage title="Post-call" />,
  },
];
