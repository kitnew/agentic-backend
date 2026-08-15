import { Link, Outlet, useRouterState } from "@tanstack/react-router";

import { featureRegistry } from "../navigation/discovery";
import { navigationUrl } from "../navigation/urls";
import { TenantSelector } from "../tenant/tenant-selector";
import { useTenant } from "../tenant/use-tenant";

export function AppShell() {
  const { tenantId } = useTenant();
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  return (
    <div className="grid min-h-screen grid-rows-[auto_1fr_auto]">
      <header className="border-b bg-panel px-4 py-3">
        <span className="font-semibold">Agent Platform</span>
        <span className="ml-2 text-sm text-muted">Admin</span>
      </header>
      <div className="grid min-h-0 md:grid-cols-[15rem_1fr]">
        <aside className="border-b bg-panel p-4 md:border-r md:border-b-0">
          <TenantSelector />
          <nav aria-label="Admin navigation" className="mt-6 space-y-5">
            {featureRegistry.navigation.map((group) => (
              <section key={group.label}>
                <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  {group.label}
                </h2>
                <ul className="space-y-1">
                  {group.items.map((item) => {
                    const to = navigationUrl(item, tenantId);
                    return (
                      <li key={item.featureId}>
                        {to ? (
                          <Link
                            className={
                              pathname === to
                                ? "block rounded px-2 py-1.5 text-sm font-medium bg-slate-100"
                                : "block rounded px-2 py-1.5 text-sm hover:bg-slate-100"
                            }
                            to={to}
                          >
                            {item.label}
                          </Link>
                        ) : (
                          <span className="block cursor-not-allowed rounded px-2 py-1.5 text-sm text-slate-400">
                            {item.label}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </nav>
        </aside>
        <main className="min-w-0 p-6">
          <div className="mb-5 text-sm text-muted">
            {tenantId ? `Tenant / ${tenantId}` : "Platform"}
          </div>
          <Outlet />
        </main>
      </div>
      <footer className="border-t px-4 py-2 text-xs text-muted">
        Admin Web V0
      </footer>
    </div>
  );
}
