import { TenantComponentEditorPage } from "../tenants/component-pages";
import { PlatformTelephonyPage } from "./telephony-page";

export const routes = [
  {
    id: "tenant-telephony",
    path: "/tenants/$tenantId/telephony",
    component: () => (
      <TenantComponentEditorPage component="telephony" title="Telephony" />
    ),
  },
  {
    id: "platform-telephony",
    path: "/platform/telephony",
    component: PlatformTelephonyPage,
  },
];
