import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { responseData } from "../api/client";
import type { ApiError } from "../api/errors";
import type {
  AuthoringIssue,
  AuthoringPlan,
  AuthoringState,
} from "../api/generated/models";

type AuthoringRequest<T> = (
  value: T,
  options?: RequestInit,
) => Promise<{ data: unknown; status: number; headers: Headers }>;

export type TenantAuthoringResource<T> = ReturnType<
  typeof useTenantAuthoringResource<T>
>;

export type AuthoringSnapshot<T> = {
  value: T;
  etag?: string | null;
  hasDraft: boolean;
};

export type AuthoringValidationState = {
  dirty: boolean;
  isValidating: boolean;
  validationFailed: boolean;
  hasBlockingValidationErrors: boolean;
  validationErrors: AuthoringIssue[];
  validationWarnings: AuthoringIssue[];
  canSave: boolean;
  remoteChanged: boolean;
  conflict: boolean;
};

export const AUTHORING_PLAN_DEBOUNCE_MS = 275;

export function semanticSerialize(value: unknown): string {
  if (value === undefined) return "undefined";
  if (value === null) return "null";
  if (Array.isArray(value))
    return `[${value.map((item) => semanticSerialize(item)).join(",")}]`;
  if (typeof value === "object")
    return `{${Object.keys(value as object)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${semanticSerialize((value as Record<string, unknown>)[key])}`,
      )
      .join(",")}}`;
  return String(JSON.stringify(value));
}

export function useTenantAuthoringResource<T>({
  queryKey,
  read,
  plan,
  save,
  emptyValue,
}: {
  queryKey: readonly unknown[];
  read: () => Promise<AuthoringState>;
  plan: (value: T) => Promise<AuthoringPlan>;
  save: AuthoringRequest<T>;
  emptyValue: T;
}) {
  const emptyValueRef = useRef(emptyValue);
  return useAuthoringResource({
    queryKey,
    read: async () => {
      const state = await read();
      return {
        value: (state.value ?? emptyValueRef.current) as T,
        etag: state.etag,
        hasDraft: state.source === "draft",
      };
    },
    plan,
    save,
  });
}

export function useAuthoringResource<T>({
  queryKey,
  read,
  plan,
  save,
}: {
  queryKey: readonly unknown[];
  read: () => Promise<AuthoringSnapshot<T>>;
  plan: (value: T) => Promise<AuthoringPlan>;
  save: AuthoringRequest<T>;
}) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey, queryFn: read });
  const [value, setValue] = useState<T>();
  const [baseline, setBaseline] = useState<string>();
  const [revision, setRevision] = useState(0);
  const [plannedRevision, setPlannedRevision] = useState<number>();
  const [remoteChanged, setRemoteChanged] = useState(false);
  const [conflict, setConflict] = useState(false);
  const valueRef = useRef<T | undefined>(undefined);
  const baselineRef = useRef<string | undefined>(undefined);
  const baselineEtagRef = useRef<string | null | undefined>(undefined);
  const revisionRef = useRef(0);
  const initialized = useRef(false);

  const acceptCanonical = useCallback(
    (snapshot: AuthoringSnapshot<T>, force = false) => {
      const nextBaseline = semanticSerialize(snapshot.value);
      const localValue = valueRef.current;
      const localDirty =
        localValue !== undefined &&
        baselineRef.current !== undefined &&
        semanticSerialize(localValue) !== baselineRef.current;
      const remoteDiffers =
        nextBaseline !== baselineRef.current ||
        snapshot.etag !== baselineEtagRef.current;

      if (force || !localDirty) {
        valueRef.current = snapshot.value;
        baselineRef.current = nextBaseline;
        baselineEtagRef.current = snapshot.etag;
        setValue(snapshot.value);
        setBaseline(nextBaseline);
        setRemoteChanged(false);
        setConflict(false);
      } else if (remoteDiffers) setRemoteChanged(true);
    },
    [],
  );

  useEffect(() => {
    if (!query.data) return;
    if (!initialized.current) {
      initialized.current = true;
      acceptCanonical(query.data, true);
    } else acceptCanonical(query.data);
  }, [acceptCanonical, query.data]);

  const setLocalValue = (next: T) => {
    valueRef.current = next;
    revisionRef.current += 1;
    setRevision(revisionRef.current);
    setValue(next);
  };

  const serialized = value === undefined ? undefined : semanticSerialize(value);
  const dirty = Boolean(serialized && baseline && serialized !== baseline);

  useEffect(() => {
    if (!dirty || value === undefined) {
      setPlannedRevision(undefined);
      return;
    }
    const timer = window.setTimeout(
      () => setPlannedRevision(revision),
      AUTHORING_PLAN_DEBOUNCE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [dirty, revision, value]);

  const candidateRevision = revision;
  const candidate = value;
  const planQuery = useQuery({
    queryKey: [...queryKey, "plan", candidateRevision],
    queryFn: () => plan(candidate as T),
    enabled:
      dirty && candidate !== undefined && plannedRevision === candidateRevision,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const validationErrors = dirty ? (planQuery.data?.errors ?? []) : [];
  const validationWarnings = dirty ? (planQuery.data?.warnings ?? []) : [];
  const isValidating =
    dirty && (plannedRevision !== candidateRevision || planQuery.isFetching);
  const validationFailed = dirty && planQuery.isError;
  const hasBlockingValidationErrors =
    dirty && (validationFailed || planQuery.data?.valid === false);
  const canSave =
    dirty &&
    !isValidating &&
    !validationFailed &&
    planQuery.data?.valid === true &&
    !conflict;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const submittedCandidate = valueRef.current;
      const submittedCandidateRevision = revisionRef.current;
      if (submittedCandidate === undefined)
        throw new Error("Authoring value is not loaded");
      const planned = await queryClient.fetchQuery({
        queryKey: [...queryKey, "plan", submittedCandidateRevision],
        queryFn: () => plan(submittedCandidate),
        staleTime: Number.POSITIVE_INFINITY,
      });
      if (!planned.valid) throw new Error("Configuration validation failed");
      const saved = responseData(
        await save(
          submittedCandidate,
          baselineEtagRef.current
            ? { headers: { "If-Match": baselineEtagRef.current } }
            : undefined,
        ),
      );
      const refreshed = await query.refetch();
      if (!refreshed.data)
        throw new Error("Authoring value could not be refreshed");
      const nextSerialized = semanticSerialize(refreshed.data.value);
      baselineRef.current = nextSerialized;
      baselineEtagRef.current = refreshed.data.etag;
      setBaseline(nextSerialized);
      if (revisionRef.current === submittedCandidateRevision) {
        valueRef.current = refreshed.data.value;
        setValue(refreshed.data.value);
      }
      setRemoteChanged(false);
      setConflict(false);
      return saved;
    },
    onError: (error) => {
      if ((error as ApiError | undefined)?.status === 412) setConflict(true);
    },
  });

  const reload = async () => {
    const refreshed = await query.refetch();
    if (!refreshed.data)
      throw new Error("Authoring value could not be refreshed");
    revisionRef.current += 1;
    setRevision(revisionRef.current);
    acceptCanonical(refreshed.data, true);
  };

  return {
    query,
    value,
    setValue: setLocalValue,
    dirty,
    hasDraft: query.data?.hasDraft ?? false,
    plan: planQuery,
    remoteChanged,
    conflict,
    reload,
    validation: {
      dirty,
      isValidating,
      validationFailed,
      hasBlockingValidationErrors,
      validationErrors,
      validationWarnings,
      canSave,
      remoteChanged,
      conflict,
    } satisfies AuthoringValidationState,
    save: saveMutation,
  };
}

export function AuthoringPlanStatus({
  validation,
  showPending = false,
}: {
  validation: AuthoringValidationState;
  showPending?: boolean;
}) {
  if (!validation.dirty) return null;
  return (
    <AuthoringValidation
      errors={validation.validationErrors}
      pending={showPending && validation.isValidating}
      requestFailed={validation.validationFailed}
      warnings={validation.validationWarnings}
    />
  );
}

export function AuthoringValidation({
  errors = [],
  warnings = [],
  requestFailed = false,
  pending = false,
}: {
  errors?: AuthoringIssue[];
  warnings?: AuthoringIssue[];
  requestFailed?: boolean;
  pending?: boolean;
}) {
  if (!errors.length && !warnings.length && !requestFailed && !pending)
    return null;
  return (
    <section
      className={`mb-4 rounded-md border p-4 text-sm ${
        errors.length || requestFailed
          ? "border-danger/20 bg-danger-soft"
          : "border-warning/20 bg-warning-soft"
      }`}
      role={errors.length || requestFailed ? "alert" : "status"}
    >
      <h2 className="font-semibold">
        {errors.length || requestFailed
          ? "Configuration needs attention"
          : pending
            ? "Checking configuration…"
            : "Configuration warnings"}
      </h2>
      {requestFailed && (
        <p className="mt-2 text-danger">
          Backend validation could not be completed.
        </p>
      )}
      {pending && <p className="mt-2 text-muted">Validating latest changes…</p>}
      <IssueList issues={errors} label="Errors" tone="text-danger" />
      <IssueList issues={warnings} label="Warnings" tone="text-warning" />
    </section>
  );
}

function IssueList({
  issues,
  label,
  tone,
}: {
  issues?: AuthoringIssue[];
  label: string;
  tone: string;
}) {
  if (!issues?.length) return null;
  return (
    <div className={`mt-2 ${tone}`}>
      <h3 className="font-medium">{label}</h3>
      <ul className="mt-1 list-disc space-y-1 pl-5">
        {issues.map((issue) => (
          <li
            data-issue-path={issue.path ?? undefined}
            key={`${issue.code}:${issue.path ?? ""}:${issue.message}`}
          >
            {issue.path ? `${issue.path}: ` : ""}
            {issue.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function authoringErrorTitle(error: unknown, fallback: string) {
  const status = (error as ApiError | undefined)?.status;
  if (status === 412)
    return "This configuration changed on the server. Reload before saving again.";
  if (status === 409)
    return "This draft conflicts with current server state. Reload before saving again.";
  return fallback;
}
