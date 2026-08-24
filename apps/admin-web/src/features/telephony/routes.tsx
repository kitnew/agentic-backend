import { DeferredFeaturePage } from "../deferred/deferred-feature-page";
import { PlatformTelephonyPage } from "./telephony-page";

export const routes = [
  {
    id: "tenant-telephony",
    path: "/tenants/$tenantId/telephony",
    component: () => <DeferredFeaturePage title="Telephony" />,
  },
  {
    id: "platform-telephony",
    path: "/platform/telephony",
    component: PlatformTelephonyPage,
  },
];
