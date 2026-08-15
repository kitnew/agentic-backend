import {
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";

import { PageError, PageLoading } from "../components/page-states";
import type { AdminFeatureRoute } from "../core/navigation/types";
import { AppShell } from "../core/shell/app-shell";

const rootRoute = createRootRoute({
  component: () => <AppShell />,
  errorComponent: ({ error }) => (
    <PageError title={error.message || "Page failed to load"} />
  ),
  pendingComponent: PageLoading,
  notFoundComponent: () => <PageError title="Page not found" />,
});
const routeModules = import.meta.glob("../features/**/routes.tsx", {
  eager: true,
  import: "routes",
}) as Record<string, AdminFeatureRoute[]>;
const definitions = Object.values(routeModules).flat() as AdminFeatureRoute[];
const routes = definitions.map((route) => {
  const Component = route.component;
  return createRoute({
    getParentRoute: () => rootRoute,
    path: route.path,
    component: () => <Component />,
  });
});
const routeTree = rootRoute.addChildren(routes);

export const router = createRouter({
  routeTree,
  defaultPendingComponent: PageLoading,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function AppRouter() {
  return <RouterProvider router={router} />;
}
