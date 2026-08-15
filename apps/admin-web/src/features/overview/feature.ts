import type { AdminFeature } from "../../core/navigation/types";

export default {
  feature: {
    id: "overview",
    scope: "global",
    navigation: { label: "Overview", to: "/", group: "Platform", order: 0 },
  } satisfies AdminFeature,
};
