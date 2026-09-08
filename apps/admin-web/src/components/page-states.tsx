import { normalizeApiError } from "../core/api/errors";
import { WorkspaceHeader } from "../core/ui/foundation";
import { Button } from "./ui/button";

export function PageLoading() {
  return (
    <p className="p-6 text-sm text-muted" role="status">
      Loading…
    </p>
  );
}

export function PageError({
  title,
  onRetry,
  compact = false,
  error,
}: {
  title: string;
  onRetry?: () => void;
  compact?: boolean;
  error?: unknown;
}) {
  const normalized = error ? normalizeApiError(error, title) : undefined;
  return (
    <div
      className={
        compact
          ? "text-sm text-red-700"
          : "rounded-md border border-red-200 bg-red-50 p-6 text-red-900"
      }
      role="alert"
    >
      <p>{title}</p>
      {normalized && normalized.message !== title && (
        <p className="mt-1">{normalized.message}</p>
      )}
      {normalized?.code && <p className="mt-1">Code: {normalized.code}</p>}
      {normalized?.issues?.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {normalized.issues.map((issue) => (
            <li key={`${issue.path}-${issue.code}-${issue.message}`}>
              {issue.path}: {issue.code}: {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
      {normalized?.requestId && (
        <p className="mt-1">Request ID: {normalized.requestId}</p>
      )}
      {onRetry && (
        <Button className="mt-3" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  return (
    <div className="rounded-md border border-dashed p-6">
      <p className="font-medium">{title}</p>
      {detail && <p className="mt-1 text-sm text-muted">{detail}</p>}
    </div>
  );
}

export function PageHeader({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  return <WorkspaceHeader description={detail} title={title} />;
}
