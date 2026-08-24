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
}: {
  title: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
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
