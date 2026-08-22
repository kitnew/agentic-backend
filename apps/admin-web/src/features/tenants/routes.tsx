import {
  TenantComponentEditorPage,
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
      <TenantComponentEditorPage component="runtime" title="Runtime" />
    ),
  },
  {
    id: "tenant-prompt",
    path: "/tenants/$tenantId/prompt",
    component: () => (
      <TenantComponentEditorPage component="prompt" title="Prompt" />
    ),
  },
  {
    id: "tenant-knowledge",
    path: "/tenants/$tenantId/knowledge-base",
    component: () => (
      <TenantComponentEditorPage component="knowledge" title="Knowledge Base" />
    ),
  },
  {
    id: "tenant-capabilities",
    path: "/tenants/$tenantId/capabilities",
    component: () => (
      <TenantComponentEditorPage
        component="capabilities"
        title="Capabilities"
      />
    ),
  },
];
