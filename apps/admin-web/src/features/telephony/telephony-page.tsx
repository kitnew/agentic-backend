import { useMutation, useQuery } from "@tanstack/react-query";

import { PageError, PageLoading } from "../../components/page-states";
import { apiErrorMessage, responseData } from "../../core/api/client";
import {
  reconcilePlatformTelephonyAdminV1PlatformTelephonyReconcilePost,
  showPlatformTelephonyAdminV1PlatformTelephonyGet,
} from "../../core/api/generated/admin-platform-telephony/admin-platform-telephony";
import type { PlatformTelephonyResponse } from "../../core/api/generated/models";
import {
  TechnicalDiagnostics,
  WorkspaceHeader,
} from "../../core/ui/foundation";

function humanize(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

function StatusBlock({
  rows,
  error,
}: {
  rows: [string, string][];
  error?: string | null;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Infrastructure status</h2>
      <div className="divide-y border-y">
        {rows.map(([label, value]) => (
          <div className="flex justify-between py-3" key={label}>
            <span>{label}</span>
            <span
              className={
                value === "ready" || value === "connected"
                  ? "text-success"
                  : "text-warning"
              }
            >
              {humanize(value)}
            </span>
          </div>
        ))}
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}

async function platformState() {
  return responseData<PlatformTelephonyResponse>(
    await showPlatformTelephonyAdminV1PlatformTelephonyGet(),
  );
}

export function PlatformTelephonyPage() {
  const query = useQuery({
    queryKey: ["admin", "platform", "telephony"],
    queryFn: platformState,
  });
  const repair = useMutation({
    mutationFn: async () =>
      responseData(
        await reconcilePlatformTelephonyAdminV1PlatformTelephonyReconcilePost(),
      ),
    onSuccess: () => query.refetch(),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        title="Platform Telephony could not be loaded"
        onRetry={() => query.refetch()}
      />
    );
  const canRepair =
    query.data.provider === "connected" && query.data.overall !== "ready";
  return (
    <>
      <WorkspaceHeader
        primaryAction={
          canRepair
            ? {
                label: "Repair",
                loading: repair.isPending,
                loadingLabel: "Repairing…",
                onClick: () => repair.mutate(),
              }
            : undefined
        }
        title="Telephony"
      />
      <div className="max-w-2xl space-y-6">
        <StatusBlock
          rows={[
            ["Provider", query.data.provider],
            ["Inbound", query.data.inbound],
            ["Outbound", query.data.outbound],
            ["Dispatch", query.data.dispatch],
            ["Overall", query.data.overall],
          ]}
          error={query.data.last_error}
        />
        {repair.isError && (
          <PageError
            compact
            title={apiErrorMessage(
              repair.error,
              "Platform Telephony repair failed.",
            )}
          />
        )}
        <section className="rounded-md border bg-slate-50 p-4">
          <h2 className="font-semibold">Trunk configuration</h2>
          <p className="mt-1 text-sm text-muted">
            Management will be available after the LiveKit provisioning contract
            is finalized.
          </p>
        </section>
        <TechnicalDiagnostics>
          <pre className="mt-3 overflow-auto">
            {JSON.stringify(query.data.diagnostics, null, 2)}
          </pre>
        </TechnicalDiagnostics>
      </div>
    </>
  );
}
