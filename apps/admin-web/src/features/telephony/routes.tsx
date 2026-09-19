import { PlatformTelephonyPage } from "./telephony-page";
import { TenantTelephonyPage } from "./tenant-page";

export const routes = [
  {
    id: "tenant-telephony",
    path: "/tenants/$tenantId/telephony",
    component: TenantTelephonyPage,
  },
  {
    id: "platform-telephony",
    path: "/platform/telephony",
    component: PlatformTelephonyPage,
  },
];
