# Admin Web V1

Static React control-plane foundation in `apps/admin-web`. Backend Core remains the Admin API authority; this application and `agentctl` consume the same exported OpenAPI schema.

## Commands

```bash
cd apps/admin-web
pnpm install --frozen-lockfile
pnpm dev
pnpm api:generate
pnpm api:check
pnpm typecheck && pnpm lint && pnpm format:check && pnpm test && pnpm build && pnpm e2e
```

`api:generate` reads the Backend and Control Plane OpenAPI snapshots; never edit either generated client tree by hand. `api:check` regenerates both and fails on a diff. CP browser paths use `/control-plane/*`; the proxy rewrites them to CP `/v1/*` and injects `CONTROL_PLANE_MANAGEMENT_TOKEN` server-side. Backend remains the owner of `/admin/*` tenant identity, sessions, and operational views. The browser never receives either management token.

## Architecture

- `src/app` owns only Router, Query, and auth-boundary providers.
- `src/core` owns platform concerns: generated API integration, error normalization, navigation, shell, and URL-derived tenancy.
- `src/features` owns product modules. Core does not import a named feature implementation.
- TanStack Query owns backend state. Context is only for stable platform dependencies; do not put API data in it.
- The tenant ID comes from `/tenants/$tenantId/...`. `useTenant()` reads that URL value; no local selected-tenant store exists.

The current backend only supports a shared bearer admin token. In deployment, Caddy authenticates the browser at the edge and injects that token only on its internal upstream request. The frontend receives neither a token nor a `VITE_*` secret. Replace this boundary with per-principal browser authentication when Backend Core provides it.

Future forms use React Hook Form plus Zod inside their feature. A backend DTO is not necessarily a UI form model: keep any UX schema and mapping in the feature.

## Agent configuration

`/tenants/$tenantId/agent` is a tenant feature discovered from `src/features/agent`; Core, AppShell, and navigation have no Agent-specific code. It maps generated Admin API DTOs to a feature-local React Hook Form/Zod model for the editable agent name, greeting, profile, locale, tenant instructions, and the supported tenant TTS voice override.

The Backend Admin API is canonical. Save creates or updates the existing versioned draft with its ETag, publishes it, and reloads canonical state; profile or tenant-prompt changes also apply the existing prompt set. Platform and profile prompt content is read-only. Capabilities are a read-only enabled summary. Infrastructure runtime settings, capabilities management, knowledge, integrations, revisions/history UI, RBAC, Debug Chat, and test calls remain out of scope.

## Add a feature

Create an isolated module—no AppShell, sidebar, or provider edit is required:

```text
src/features/foo/
  feature.ts
  routes.tsx
  pages/
  components/
  queries/
  schemas/
```

```ts
// src/features/foo/feature.ts
export default {
  feature: {
    id: "foo",
    scope: "tenant",
    navigation: { label: "Foo", to: "/tenants/$tenantId/foo", group: "Configuration", order: 50 },
    permissions: ["tenant.foo.read"],
  },
} satisfies AdminFeature;
```

Export its route definitions from `routes.tsx`. Vite discovers both manifests and route modules at build time. Permission filtering has one future insertion point at the generated feature navigation registry; V0 treats the edge-authenticated operator as an administrator.

## Deployment

`Dockerfile` builds Vite assets and serves them from an unprivileged Nginx container. Deploy Compose puts it behind Caddy on `ADMIN_WEB_DOMAIN`; the browser calls the Admin API on the same origin at `/admin/v1/...`. Local `pnpm dev` gives Vite HMR and proxies that path to `localhost:8000`.
