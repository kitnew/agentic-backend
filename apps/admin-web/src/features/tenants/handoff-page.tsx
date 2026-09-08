import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { managementMutationOptions, responseData } from "../../core/api/client";
import {
  createHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsPost,
  disableHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdDisablePost,
  enableHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdEnablePost,
  getHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdGet,
  listHandoffDestinationsManagementV1TenantsTenantIdTelephonyHandoffDestinationsGet,
  updateHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdPut,
} from "../../core/api/control-plane";
import { useTenant } from "../../core/tenant/use-tenant";

export function HandoffPage() {
  const { tenantId } = useTenant();
  const [key, setKey] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [description, setDescription] = useState("");
  const query = useQuery({
    queryKey: ["control-plane", "handoff", tenantId],
    enabled: Boolean(tenantId),
    queryFn: async () =>
      responseData<unknown[]>(
        await listHandoffDestinationsManagementV1TenantsTenantIdTelephonyHandoffDestinationsGet(
          tenantId as string,
        ),
      ),
  });
  const refresh = () => query.refetch();
  const create = useMutation({
    mutationFn: () =>
      createHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsPost(
        tenantId as string,
        { key, phone_number: phoneNumber, description },
        managementMutationOptions(),
      ),
    onSuccess: () => {
      setKey("");
      setPhoneNumber("");
      setDescription("");
      refresh();
    },
  });
  if (!tenantId) return <PageError title="Select a tenant first" />;
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return <PageError title="Handoff destinations could not be loaded" />;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Handoff"
        detail="Handoff destinations are managed resources; changes apply immediately."
      />
      <form
        className="grid gap-3 rounded border p-4 md:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <input
          aria-label="Key"
          className="rounded border p-2"
          placeholder="Key"
          value={key}
          onChange={(event) => setKey(event.target.value)}
        />
        <input
          aria-label="Phone number"
          className="rounded border p-2"
          placeholder="Phone number"
          value={phoneNumber}
          onChange={(event) => setPhoneNumber(event.target.value)}
        />
        <input
          aria-label="Description"
          className="rounded border p-2"
          placeholder="Description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white md:col-span-3"
          disabled={!key || !phoneNumber || !description || create.isPending}
          type="submit"
        >
          Create destination
        </button>
      </form>
      <ul className="divide-y border-y">
        {query.data.map((item) => {
          const resource = item as Record<string, unknown>;
          const id = String(
            resource.resource_id ?? resource.id ?? resource.key,
          );
          const enabled = resource.enabled !== false;
          return (
            <li
              className="flex flex-wrap items-center justify-between gap-3 py-3"
              key={id}
            >
              <span>
                <strong>{String(resource.key ?? id)}</strong>
                <span className="ml-2 text-sm text-muted">
                  {String(resource.phone_number ?? "")} ·{" "}
                  {enabled ? "Enabled" : "Disabled"}
                </span>
              </span>
              <span className="flex gap-2">
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={async () => {
                    const current =
                      await getHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdGet(
                        tenantId,
                        id,
                      );
                    const operation = enabled
                      ? disableHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdDisablePost
                      : enableHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdEnablePost;
                    await operation(
                      tenantId,
                      id,
                      managementMutationOptions(current.headers.get("etag")),
                    );
                    await refresh();
                  }}
                  type="button"
                >
                  {enabled ? "Disable" : "Enable"}
                </button>
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={async () => {
                    const current =
                      await getHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdGet(
                        tenantId,
                        id,
                      );
                    await updateHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdPut(
                      tenantId,
                      id,
                      {
                        description: String(
                          resource.description ?? description,
                        ),
                        phone_number: String(
                          resource.phone_number ?? phoneNumber,
                        ),
                      },
                      managementMutationOptions(current.headers.get("etag")),
                    );
                    await refresh();
                  }}
                  type="button"
                >
                  Save current
                </button>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
