import { Link, Outlet, useRouterState } from "@tanstack/react-router";

import { useTenant } from "../tenant/use-tenant";
import { useTenants } from "../tenant/use-tenants";

const mainNavigation = [
  { label: "Overview", to: "/" },
  { label: "Platform", to: "/platform" },
  { label: "Tenants", to: "/tenants" },
] as const;

const platformNavigation = [
  { label: "Runtime", to: "/platform/runtime" },
  { label: "Telephony", to: "/platform/telephony" },
  { label: "System Prompt", to: "/platform/system-prompt" },
  { label: "Profile Prompt", to: "/platform/profile-prompt" },
] as const;

const tenantNavigation = [
  { label: "Runtime", suffix: "/runtime" },
  { label: "Telephony", suffix: "/telephony" },
  { label: "Agent", suffix: "/agent" },
  { label: "Prompt", suffix: "/prompt" },
  { label: "Knowledge Base", suffix: "/knowledge-base" },
  { label: "Capabilities", suffix: "/capabilities" },
  { label: "Playground", suffix: "/playground" },
] as const;

function NavLink({ to, label }: { to: string; label: string }) {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const active = pathname === to;
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={
        active
          ? "block rounded-md bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-950"
          : "block rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 hover:text-slate-950"
      }
      to={to as never}
    >
      {label}
    </Link>
  );
}

function WorkspaceNavigation() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const { tenantId } = useTenant();
  const tenants = useTenants();
  if (pathname.startsWith("/platform"))
    return (
      <aside className="border-b bg-slate-50/70 p-4 md:border-r md:border-b-0 md:p-6">
        <Link
          className="mb-4 block px-3 font-semibold"
          to={"/platform" as never}
        >
          Platform
        </Link>
        <nav aria-label="Platform navigation" className="space-y-1">
          {platformNavigation.map((item) => (
            <NavLink key={item.to} {...item} />
          ))}
        </nav>
      </aside>
    );
  if (tenantId) {
    const tenant = tenants.data?.find((item) => item.id === tenantId);
    return (
      <aside className="border-b bg-slate-50/70 p-4 md:border-r md:border-b-0 md:p-6">
        <Link
          className="mb-4 block truncate px-3 font-semibold"
          to={`/tenants/${tenantId}` as never}
        >
          {tenant?.display_name ?? "Tenant"}
        </Link>
        <nav aria-label="Tenant navigation" className="space-y-1">
          {tenantNavigation.map((item) => (
            <NavLink
              key={item.suffix}
              label={item.label}
              to={`/tenants/${tenantId}${item.suffix}`}
            />
          ))}
        </nav>
      </aside>
    );
  }
  return null;
}

export function AppShell() {
  const grafanaUrl = import.meta.env.VITE_GRAFANA_URL?.trim();
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const workspace =
    pathname.startsWith("/platform") || /^\/tenants\/[^/]+/.test(pathname);
  return (
    <div className="min-h-screen bg-background md:grid md:grid-cols-[14rem_1fr]">
      <aside className="border-b bg-slate-950 p-4 text-white md:min-h-screen md:border-b-0 md:p-6">
        <div className="mb-7 text-lg font-semibold tracking-tight">
          Agent Platform
        </div>
        <nav aria-label="Main navigation" className="space-y-1">
          {mainNavigation.map((item) => {
            const active =
              item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={
                  active
                    ? "block rounded-md bg-white/12 px-3 py-2 text-sm font-semibold"
                    : "block rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-white/8 hover:text-white"
                }
                key={item.to}
                to={item.to as never}
              >
                {item.label}
              </Link>
            );
          })}
          <a
            aria-disabled={!grafanaUrl}
            className="block rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-white/8 hover:text-white"
            href={grafanaUrl || "#"}
            rel="noreferrer"
            target="_blank"
          >
            Observability ↗
          </a>
        </nav>
      </aside>
      <div className={workspace ? "md:grid md:grid-cols-[14rem_1fr]" : ""}>
        <WorkspaceNavigation />
        <main className="min-w-0 p-5 md:p-8 lg:p-10">
          <div className="mx-auto max-w-5xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
