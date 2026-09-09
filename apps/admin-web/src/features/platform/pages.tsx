import { Link } from "@tanstack/react-router";

import { PageHeader } from "../../components/page-states";
import {
  PlatformConfigurationEditor,
  SystemConfigurationEditor,
} from "../../core/configuration/high-level";

export function PlatformOverviewPage() {
  return (
    <>
      <PageHeader
        title="Platform"
        detail="Control Plane configuration and Backend operational status are managed separately."
      />
      <div className="grid gap-3 md:grid-cols-2">
        <Link
          className="rounded border p-4"
          to={"/platform/system-configuration" as never}
        >
          System Configuration
          <span className="mt-1 block text-sm text-muted">
            Five independent CP components
          </span>
        </Link>
        <Link
          className="rounded border p-4"
          to={"/platform/configuration" as never}
        >
          Platform Configuration
          <span className="mt-1 block text-sm text-muted">
            System and profile-scoped prompts
          </span>
        </Link>
        <Link
          className="rounded border p-4"
          to={"/platform/providers" as never}
        >
          Providers
          <span className="mt-1 block text-sm text-muted">
            Credentials, connections, deployments
          </span>
        </Link>
        <Link
          className="rounded border p-4"
          to={"/platform/telephony" as never}
        >
          Telephony Diagnostics
          <span className="mt-1 block text-sm text-muted">
            Backend operational topology
          </span>
        </Link>
      </div>
    </>
  );
}

export function PlatformRuntimePage() {
  return <SystemConfigurationEditor />;
}

export function PlatformSystemConfigurationPage() {
  return <SystemConfigurationEditor />;
}

export function PlatformConfigurationPage() {
  return <PlatformConfigurationEditor />;
}

export function PlatformSystemPromptPage() {
  return <PlatformConfigurationEditor />;
}

export function PlatformProfilePromptPage() {
  return <PlatformConfigurationEditor />;
}
