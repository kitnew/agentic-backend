import { WorkspaceHeader } from "../../core/ui/foundation";

export function DeferredFeaturePage({ title }: { title: string }) {
  return (
    <div className="max-w-4xl">
      <WorkspaceHeader title={title} />
      <section className="rounded-md border p-6">
        <h2 className="font-semibold">
          Feature temporarily unavailable in Admin Web
        </h2>
        <p className="mt-2 text-sm text-muted">
          Use agentctl for configuration and management until the Admin Web
          domain model is finalized.
        </p>
      </section>
    </div>
  );
}
