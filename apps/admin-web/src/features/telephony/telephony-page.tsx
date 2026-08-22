import { useMutation, useQuery } from "@tanstack/react-query";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { Button } from "../../components/ui/button";
import { responseData } from "../../core/api/client";
import {
  reconcilePlatformTelephonyAdminV1PlatformTelephonyReconcilePost,
  showPlatformTelephonyAdminV1PlatformTelephonyGet,
} from "../../core/api/generated/admin-platform-telephony/admin-platform-telephony";
import type { PlatformTelephonyResponse } from "../../core/api/generated/models";

function StatusBlock({
  rows,
  error,
}: {
  rows: [string, string][];
  error?: string | null;
}) {
  return (
    <section className="space-y-3 border-t pt-6">
      <h2 className="text-lg font-semibold">Status</h2>
      <div className="divide-y border-y">
        {rows.map(([label, value]) => (
          <div className="flex justify-between py-3" key={label}>
            <span>{label.replaceAll("_", " ")}</span>
            <span
              className={
                value === "ready" || value === "connected"
                  ? "text-emerald-700"
                  : "text-amber-700"
              }
            >
              {value}
            </span>
          </div>
        ))}
      </div>
      {error && <p className="text-sm text-red-700">{error}</p>}
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
  return (
    <>
      <PageHeader title="Telephony" />
      <div className="max-w-2xl space-y-6">
        <StatusBlock
          rows={[
            ["provider", query.data.provider],
            ["inbound", query.data.inbound],
            ["outbound", query.data.outbound],
            ["dispatch", query.data.dispatch],
            ["overall", query.data.overall],
          ]}
          error={query.data.last_error}
        />
        <Button disabled={repair.isPending} onClick={() => repair.mutate()}>
          {repair.isPending ? "Repairing..." : "Repair"}
        </Button>
        <details className="text-sm text-muted">
          <summary>Technical diagnostics</summary>
          <pre className="mt-3 overflow-auto">
            {JSON.stringify(query.data.diagnostics, null, 2)}
          </pre>
        </details>
      </div>
    </>
  );
}
