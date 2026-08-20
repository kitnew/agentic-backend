import {
  CapabilitiesPage,
  KnowledgeBasePage,
  TenantOverviewPage,
  TenantPromptPage,
  TenantRuntimePage,
  TenantsPage,
} from "./pages";

export const routes = [
  { id: "tenants", path: "/tenants", component: TenantsPage },
  {
    id: "tenant-overview",
    path: "/tenants/$tenantId",
    component: TenantOverviewPage,
  },
  {
    id: "tenant-runtime",
    path: "/tenants/$tenantId/runtime",
    component: TenantRuntimePage,
  },
  {
    id: "tenant-prompt",
    path: "/tenants/$tenantId/prompt",
    component: TenantPromptPage,
  },
  {
    id: "tenant-knowledge",
    path: "/tenants/$tenantId/knowledge-base",
    component: KnowledgeBasePage,
  },
  {
    id: "tenant-capabilities",
    path: "/tenants/$tenantId/capabilities",
    component: CapabilitiesPage,
  },
];
