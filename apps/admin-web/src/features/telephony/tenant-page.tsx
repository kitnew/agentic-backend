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
  disablePhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsIdDisablePost,
  enablePhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsIdEnablePost,
  getPhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsIdGet,
  listPhoneNumberAssignmentsManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsGet,
} from "../../core/api/control-plane";
import type { PhoneNumberAssignmentResponse } from "../../core/api/control-plane/generated/models";
import { tenantTelephonyStatusAdminV1TenantsTenantIdTelephonyStatusGet } from "../../core/api/generated/admin-tenants/admin-tenants";
import type { TenantTelephonyStatus } from "../../core/api/generated/models";
import { useTenant } from "../../core/tenant/use-tenant";

export function TenantTelephonyPage() {
  const { tenantId } = useTenant();
  const [phone, setPhone] = useState("");
  const assignments = useQuery({
    queryKey: ["control-plane", "phone-assignments", tenantId],
    enabled: Boolean(tenantId),
    queryFn: async () =>
      responseData<PhoneNumberAssignmentResponse[]>(
        await listPhoneNumberAssignmentsManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsGet(
          tenantId as string,
        ),
      ),
  });
  const operational = useQuery({
    queryKey: ["backend", "telephony-status", tenantId],
    enabled: Boolean(tenantId),
    queryFn: async () =>
      responseData<TenantTelephonyStatus>(
        await tenantTelephonyStatusAdminV1TenantsTenantIdTelephonyStatusGet(
          tenantId as string,
        ),
      ),
  });
  const assign = useMutation({
    mutationFn: async () => {
      const createdResponse =
        await createPhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsPost(
          tenantId as string,
          { phone_number: phone },
          managementMutationOptions(),
        );
      const created =
        responseData<PhoneNumberAssignmentResponse>(createdResponse);
      if (created.enabled) return createdResponse;
      const etag = createdResponse.headers.get("etag");
      if (!etag) throw new Error("DID assignment response has no ETag");
      return responseData(
        await enablePhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsIdEnablePost(
          tenantId as string,
          created.id,
          managementMutationOptions(etag),
        ),
      );
    },
    onSuccess: () => {
      setPhone("");
      assignments.refetch();
      operational.refetch();
    },
  });
  const toggle = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => {
      const current =
        await getPhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsIdGet(
          tenantId as string,
          id,
        );
      const assignment = responseData<PhoneNumberAssignmentResponse>(current);
      if (assignment.enabled === enabled) return;
      const etag = current.headers.get("etag");
      if (!etag) throw new Error("DID assignment response has no ETag");
      const operation = enabled
        ? enablePhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsIdEnablePost
        : disablePhoneNumberAssignmentManagementV1TenantsTenantIdTelephonyPhoneNumberAssignmentsIdDisablePost;
      responseData(
        await operation(
          tenantId as string,
          id,
          managementMutationOptions(etag),
        ),
      );
    },
    onSuccess: () => {
      assignments.refetch();
      operational.refetch();
    },
  });
  if (!tenantId) return <PageError title="Select a tenant first" />;
  if (assignments.isPending || operational.isPending) return <PageLoading />;
  if (assignments.isError || operational.isError)
    return <PageError title="Telephony status could not be loaded" />;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Telephony"
        detail="Every enabled DID is configured as an inbound route for this tenant. Disable a DID to remove it on reconciliation."
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
          Add DID
        </button>
      </form>
      <section>
        <h2 className="mb-2 font-semibold">Inbound DIDs</h2>
        <ul className="divide-y rounded border">
          {assignments.data.map((assignment) => (
            <li
              className="flex items-center justify-between gap-3 p-3"
              key={assignment.id}
            >
              <span>
                <strong>{assignment.phone_number}</strong>{" "}
                <span className="text-sm text-muted">
                  {assignment.enabled
                    ? "Enabled — assigned to this tenant"
                    : "Disabled"}
                </span>
              </span>
              <button
                className="rounded border px-3 py-1 text-sm"
                disabled={toggle.isPending}
                onClick={() =>
                  toggle.mutate({
                    id: assignment.id,
                    enabled: !assignment.enabled,
                  })
                }
                type="button"
              >
                {assignment.enabled ? "Disable" : "Enable"}
              </button>
            </li>
          ))}
        </ul>
        {assignments.data.length === 0 && <p>No inbound DIDs assigned.</p>}
      </section>
      <section>
        <h2 className="mb-2 font-semibold">Operational reconciliation</h2>
        <p>Provisioning: {operational.data.provisioning.state}</p>
        {operational.data.provisioning.last_error && (
          <p>{operational.data.provisioning.last_error}</p>
        )}
        <details>
          <summary>Technical status</summary>
          <p className="text-sm text-muted">
            The published and claim fields summarize only the first enabled DID.
            All enabled DIDs are listed above.
          </p>
          <pre className="overflow-auto rounded border p-3 text-sm">
            {JSON.stringify(operational.data, null, 2)}
          </pre>
        </details>
      </section>
      {(assign.isError || toggle.isError) && (
        <PageError
          compact
          title="Phone assignment could not be changed"
          error={assign.error ?? toggle.error}
        />
      )}
    </div>
  );
}
