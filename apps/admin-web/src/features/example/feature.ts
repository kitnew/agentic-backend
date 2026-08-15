import type { AdminFeature } from "../../core/navigation/types";

export default {
  feature: {
    id: "example",
    scope: "tenant",
    navigation: {
      label: "Example",
      to: "/tenants/$tenantId/example",
      group: "Tenant",
      order: 0,
    },
    permissions: ["tenant.example.read"],
  } satisfies AdminFeature,
};
