import { PlatformTelephonyPage, TenantTelephonyPage } from "./telephony-page";

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
