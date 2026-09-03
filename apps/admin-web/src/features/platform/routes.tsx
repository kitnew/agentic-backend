import {
  PlatformOverviewPage,
  PlatformProfilePromptPage,
  PlatformRuntimePage,
  PlatformSystemPromptPage,
} from "./pages";
import { PlatformProvidersPage } from "./providers-page";

export const routes = [
  { id: "platform", path: "/platform", component: PlatformOverviewPage },
  {
    id: "platform-runtime",
    path: "/platform/runtime",
    component: PlatformRuntimePage,
  },
  {
    id: "platform-system-prompt",
    path: "/platform/system-prompt",
    component: PlatformSystemPromptPage,
  },
  {
    id: "platform-profile-prompt",
    path: "/platform/profile-prompt",
    component: PlatformProfilePromptPage,
  },
  {
    id: "platform-providers",
    path: "/platform/providers",
    component: PlatformProvidersPage,
  },
];
