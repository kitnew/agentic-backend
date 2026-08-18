import { AgentPage } from "./pages/agent-page";

export const routes = [
	{ id: "agent", path: "/tenants/$tenantId/agent", component: AgentPage },
];
