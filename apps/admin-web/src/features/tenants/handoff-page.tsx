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
    mutationFn: async () =>
      responseData(
        await createHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsPost(
          tenantId as string,
          { key, phone_number: phoneNumber, description },
          managementMutationOptions(),
        ),
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
      {create.isError && (
        <PageError
          compact
          title="Destination could not be created"
          error={create.error}
        />
      )}
      <ul className="divide-y border-y">
        {query.data.map((item) => {
          const resource = item as Record<string, unknown>;
          return (
            <DestinationRow
              key={String(resource.resource_id ?? resource.id ?? resource.key)}
              resource={resource}
              tenantId={tenantId}
              refresh={refresh}
            />
          );
        })}
      </ul>
    </div>
  );
}

function DestinationRow({
  resource,
  tenantId,
  refresh,
}: {
  resource: Record<string, unknown>;
  tenantId: string;
  refresh: () => unknown;
}) {
  const id = String(resource.resource_id ?? resource.id ?? resource.key);
  const destinationKey = String(resource.key ?? id);
  const enabled = resource.enabled !== false;
  const [edit, setEdit] = useState<{
    phoneNumber: string;
    description: string;
    etag: string;
    dirty: boolean;
  } | null>(null);
  const open = useMutation({
    mutationFn: async () => {
      const current =
        await getHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdGet(
          tenantId,
          id,
        );
      const value = responseData<{
        phone_number: string;
        description: string;
      }>(current);
      const etag = current.headers.get("etag");
      if (!etag) throw new Error("Destination ETag is missing");
      return {
        phoneNumber: value.phone_number,
        description: value.description,
        etag,
        dirty: false,
      };
    },
    onSuccess: setEdit,
  });
  const save = useMutation({
    mutationFn: async (changes: NonNullable<typeof edit>) =>
      responseData(
        await updateHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdPut(
          tenantId,
          id,
          {
            description: changes.description,
            phone_number: changes.phoneNumber,
          },
          managementMutationOptions(changes.etag),
        ),
      ),
    onSuccess: () => {
      setEdit(null);
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: async () => {
      const current =
        await getHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdGet(
          tenantId,
          id,
        );
      responseData(current);
      const operation = enabled
        ? disableHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdDisablePost
        : enableHandoffDestinationManagementV1TenantsTenantIdTelephonyHandoffDestinationsIdEnablePost;
      return responseData(
        await operation(
          tenantId,
          id,
          managementMutationOptions(current.headers.get("etag")),
        ),
      );
    },
    onSuccess: refresh,
  });
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <strong>{destinationKey}</strong>
        <span className="text-sm text-muted">
          {enabled ? "Enabled" : "Disabled"}
        </span>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {edit ? (
          <>
            <label className="text-sm">
              Phone number
              <input
                aria-label={`${destinationKey} phone number`}
                className="block rounded border p-2"
                value={edit.phoneNumber}
                onChange={(event) =>
                  setEdit({
                    ...edit,
                    phoneNumber: event.target.value,
                    dirty: true,
                  })
                }
              />
            </label>
            <label className="text-sm">
              Description
              <input
                aria-label={`${destinationKey} description`}
                className="block rounded border p-2"
                value={edit.description}
                onChange={(event) =>
                  setEdit({
                    ...edit,
                    description: event.target.value,
                    dirty: true,
                  })
                }
              />
            </label>
            <button
              className="rounded border px-2 py-1 text-sm"
              disabled={
                save.isPending ||
                !edit.dirty ||
                !edit.phoneNumber ||
                !edit.description
              }
              onClick={() => save.mutate(edit)}
              type="button"
            >
              Save changes
            </button>
            <button
              className="rounded border px-2 py-1 text-sm"
              disabled={save.isPending}
              onClick={() => {
                setEdit(null);
                save.reset();
              }}
              type="button"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <span className="text-sm">
              {String(resource.phone_number ?? "")} ·{" "}
              {String(resource.description ?? "")}
            </span>
            <button
              className="rounded border px-2 py-1 text-sm"
              disabled={open.isPending || toggle.isPending}
              onClick={() => open.mutate()}
              type="button"
            >
              Edit
            </button>
          </>
        )}
        <button
          className="rounded border px-2 py-1 text-sm"
          disabled={toggle.isPending || open.isPending || Boolean(edit)}
          onClick={() => toggle.mutate()}
          type="button"
        >
          {enabled ? "Disable" : "Enable"}
        </button>
      </div>
      {save.isError && (
        <PageError
          compact
          title="Destination could not be updated"
          error={save.error}
        />
      )}
      {open.isError && (
        <PageError
          compact
          title="Destination could not be loaded"
          error={open.error}
        />
      )}
      {toggle.isError && (
        <PageError
          compact
          title="Destination status could not be changed"
          error={toggle.error}
        />
      )}
    </li>
  );
}
