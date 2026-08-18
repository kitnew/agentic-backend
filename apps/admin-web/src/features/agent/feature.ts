import type { AdminFeature } from "../../core/navigation/types";

export default {
	feature: {
		id: "agent",
		scope: "tenant",
		navigation: {
			label: "Agent",
			to: "/tenants/$tenantId/agent",
			group: "Configuration",
			order: 10,
		},
		permissions: ["tenant.agent.read", "tenant.agent.write"],
	} satisfies AdminFeature,
};
