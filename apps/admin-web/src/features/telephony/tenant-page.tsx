import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { managementMutationOptions, responseData } from "../../core/api/client";
import {
  createPhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsPost,
  listPhoneNumberAssignmentsManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsGet,
} from "../../core/api/control-plane";
import { tenantTelephonyStatusAdminV1TenantsTenantIdTelephonyStatusGet } from "../../core/api/generated/admin-tenants/admin-tenants";
import { useTenant } from "../../core/tenant/use-tenant";

export function TenantTelephonyPage() {
  const { tenantId } = useTenant();
  const [phone, setPhone] = useState("");
  const assignments = useQuery({
    queryKey: ["control-plane", "phone-assignments", tenantId],
    enabled: Boolean(tenantId),
    queryFn: async () =>
      responseData<unknown[]>(
        await listPhoneNumberAssignmentsManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsGet(
          tenantId as string,
        ),
      ),
  });
  const operational = useQuery({
    queryKey: ["backend", "telephony-status", tenantId],
    enabled: Boolean(tenantId),
    queryFn: async () =>
      responseData<unknown>(
        await tenantTelephonyStatusAdminV1TenantsTenantIdTelephonyStatusGet(
          tenantId as string,
        ),
      ),
  });
  const assign = useMutation({
    mutationFn: () =>
      createPhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsPost(
        tenantId as string,
        { phone_number: phone },
        managementMutationOptions(),
      ),
    onSuccess: () => {
      setPhone("");
      assignments.refetch();
      operational.refetch();
    },
  });
  if (!tenantId) return <PageError title="Select a tenant first" />;
  if (assignments.isPending || operational.isPending) return <PageLoading />;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Telephony"
        detail="Desired phone assignment is Control Plane state; reconciliation and readiness are Backend operational state."
      />
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          assign.mutate();
        }}
      >
        <input
          aria-label="Phone number"
          className="rounded border p-2"
          placeholder="+421..."
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
        />
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white"
          disabled={!phone || assign.isPending}
          type="submit"
        >
          Assign DID
        </button>
      </form>
      <section>
        <h2 className="mb-2 font-semibold">Desired assignment</h2>
        <pre className="overflow-auto rounded border p-3 text-sm">
          {JSON.stringify(assignments.data, null, 2)}
        </pre>
      </section>
      <section>
        <h2 className="mb-2 font-semibold">Operational reconciliation</h2>
        <pre className="overflow-auto rounded border p-3 text-sm">
          {JSON.stringify(operational.data, null, 2)}
        </pre>
      </section>
      {assign.isError && (
        <PageError compact title="Phone assignment could not be changed" />
      )}
    </div>
  );
}
