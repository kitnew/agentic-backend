import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  EmptyState,
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
import {
  publishConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPublishPost,
  saveTenantTelephonyAdminV1TenantsTenantIdTelephonyPut,
  showTenantTelephonyAdminV1TenantsTenantIdTelephonyGet,
} from "../../core/api/generated/admin-tenants/admin-tenants";
import type {
  HandoffDestination,
  PlatformTelephonyResponse,
  TenantTelephonyResponse,
  TenantTelephonyUpdate,
} from "../../core/api/generated/models";
import { EditorActions, Field } from "../../core/configuration/editor";
import { useTenant } from "../../core/tenant/use-tenant";

const e164 = /^\+[1-9]\d{1,14}$/;
type Destination = HandoffDestination & { id: string; key: string };

const tenantKey = (tenantId: string) => ["admin", "telephony", tenantId];

async function tenantState(tenantId: string) {
  return responseData<TenantTelephonyResponse>(
    await showTenantTelephonyAdminV1TenantsTenantIdTelephonyGet(tenantId),
  );
}

export function TenantTelephonyPage() {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  return <TenantTelephonyContents tenantId={tenantId} />;
}

function TenantTelephonyContents({ tenantId }: { tenantId: string }) {
  const query = useQuery({
    queryKey: tenantKey(tenantId),
    queryFn: () => tenantState(tenantId),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        title="Telephony could not be loaded"
        onRetry={() => query.refetch()}
      />
    );
  return (
    <TenantTelephonyEditor
      key={JSON.stringify(query.data)}
      state={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function TenantTelephonyEditor({
  state,
  refetch,
}: {
  state: TenantTelephonyResponse;
  refetch: () => Promise<void>;
}) {
  const [phoneNumber, setPhoneNumber] = useState(
    state.desired.phone_number ?? "",
  );
  const [destinations, setDestinations] = useState<Destination[]>(
    Object.entries(state.desired.handoff?.destinations ?? {}).map(
      ([key, value]) => ({
        id: crypto.randomUUID(),
        key,
        ...(value as HandoffDestination),
      }),
    ),
  );
  const request: TenantTelephonyUpdate = {
    phone_number: phoneNumber || null,
    handoff: {
      destinations: Object.fromEntries(
        destinations.map((destination) => [
          destination.key,
          {
            description: destination.description,
            phone_number: destination.phone_number,
          },
        ]),
      ),
    },
  };
  const initial = JSON.stringify(state.desired);
  const dirty = JSON.stringify(request) !== initial;
  const valid =
    (!phoneNumber || e164.test(phoneNumber)) &&
    destinations.every(
      (item) =>
        /^[a-z][a-z0-9_]{0,63}$/.test(item.key) &&
        item.description.trim() &&
        e164.test(item.phone_number),
    ) &&
    new Set(destinations.map((item) => item.key)).size === destinations.length;
  const save = useMutation({
    mutationFn: async () => {
      responseData(
        await saveTenantTelephonyAdminV1TenantsTenantIdTelephonyPut(
          state.tenant_id,
          request,
          state.draft_version == null
            ? undefined
            : { headers: { "If-Match": `"${state.draft_version}"` } },
        ),
      );
      await refetch();
    },
  });
  const publish = useMutation({
    mutationFn: async () => {
      responseData(
        await publishConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPublishPost(
          state.tenant_id,
          state.draft_revision_id ?? "",
        ),
      );
      await refetch();
    },
  });
  const updateDestination = (index: number, change: Partial<Destination>) =>
    setDestinations(
      destinations.map((item, i) =>
        i === index ? { ...item, ...change } : item,
      ),
    );
  return (
    <>
      <PageHeader title="Telephony" />
      <div className="max-w-3xl space-y-8">
        <EditorActions
          dirty={dirty}
          hasDraft={Boolean(state.draft_revision_id)}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() =>
            valid
              ? save.mutateAsync()
              : Promise.reject(new Error("Invalid telephony"))
          }
          onPublish={() => publish.mutateAsync()}
        />
        {state.draft_revision_id && (
          <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            Saved changes are not published yet. Runtime calls and readiness
            still use the published Telephony configuration.
          </p>
        )}
        <Field
          label="Phone number"
          detail="Used for incoming calls and as the caller ID for outbound handoff."
        >
          <input
            type="tel"
            pattern="\+[1-9][0-9]{1,14}"
            placeholder="+421551234567"
            value={phoneNumber}
            onChange={(event) => setPhoneNumber(event.target.value.trim())}
          />
        </Field>
        <section className="space-y-4 border-t pt-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Handoff destinations</h2>
            <Button
              variant="outline"
              onClick={() =>
                setDestinations([
                  ...destinations,
                  {
                    id: crypto.randomUUID(),
                    key: `destination_${destinations.length + 1}`,
                    description: "",
                    phone_number: "",
                  },
                ])
              }
            >
              Add destination
            </Button>
          </div>
          {destinations.map((destination, index) => (
            <div
              className="grid gap-4 rounded-md border p-4 sm:grid-cols-2"
              key={destination.id}
            >
              <Field label="Semantic key">
                <input
                  value={destination.key}
                  onChange={(event) =>
                    updateDestination(index, { key: event.target.value })
                  }
                />
              </Field>
              <Field label="Label">
                <input
                  value={destination.description}
                  onChange={(event) =>
                    updateDestination(index, {
                      description: event.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Phone number">
                <input
                  type="tel"
                  pattern="\+[1-9][0-9]{1,14}"
                  value={destination.phone_number}
                  onChange={(event) =>
                    updateDestination(index, {
                      phone_number: event.target.value.trim(),
                    })
                  }
                />
              </Field>
              <div className="flex items-end">
                <Button
                  variant="ghost"
                  onClick={() =>
                    setDestinations(destinations.filter((_, i) => i !== index))
                  }
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </section>
        <StatusBlock
          rows={Object.entries(state.readiness)}
          error={state.last_error}
        />
        {!valid && (
          <PageError
            compact
            title="Use unique semantic keys and valid E.164 phone numbers"
          />
        )}
        {(save.isError || publish.isError) && (
          <PageError compact title="Telephony change failed" />
        )}
      </div>
    </>
  );
}

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
