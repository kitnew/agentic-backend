import { useBlocker } from "@tanstack/react-router";
import {
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
  useId,
  useState,
} from "react";

import { Button } from "../../components/ui/button";

export type ConfigurationStatus =
  | "Published"
  | "Unsaved changes"
  | "Saved · Not published"
  | "Saving..."
  | "Publishing...";

export function EditorActions({
  dirty,
  hasDraft,
  saving,
  publishing,
  onSave,
  onPublish,
}: {
  dirty: boolean;
  hasDraft: boolean;
  saving: boolean;
  publishing: boolean;
  onSave: () => Promise<void>;
  onPublish: () => Promise<void>;
}) {
  const [navigationSave, setNavigationSave] = useState(false);
  const blocker = useBlocker({
    shouldBlockFn: () => dirty,
    enableBeforeUnload: dirty,
    withResolver: true,
  });
  const status: ConfigurationStatus = saving
    ? "Saving..."
    : publishing
      ? "Publishing..."
      : dirty
        ? "Unsaved changes"
        : hasDraft
          ? "Saved · Not published"
          : "Published";

  async function saveAndContinue() {
    setNavigationSave(true);
    try {
      await onSave();
      blocker.proceed?.();
    } finally {
      setNavigationSave(false);
    }
  }

  return (
    <>
      <div className="mb-7 flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <StatusBadge status={status} />
        <div className="flex gap-2">
          <Button disabled={!dirty || saving || publishing} onClick={onSave}>
            Save
          </Button>
          <Button
            disabled={dirty || !hasDraft || saving || publishing}
            onClick={onPublish}
            variant="outline"
          >
            Publish
          </Button>
        </div>
      </div>
      {blocker.status === "blocked" && (
        <div
          aria-labelledby="unsaved-title"
          aria-modal="true"
          className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4"
          role="dialog"
        >
          <div className="w-full max-w-md rounded-lg bg-panel p-6 shadow-xl">
            <h2 className="text-lg font-semibold" id="unsaved-title">
              Unsaved changes
            </h2>
            <p className="mt-2 text-sm text-muted">
              You have changes that have not been saved.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button onClick={() => blocker.reset?.()} variant="ghost">
                Stay
              </Button>
              <Button onClick={() => blocker.proceed?.()} variant="outline">
                Discard changes
              </Button>
              <Button disabled={navigationSave} onClick={saveAndContinue}>
                {navigationSave ? "Saving..." : "Save and continue"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function StatusBadge({ status }: { status: ConfigurationStatus }) {
  const tone = status === "Published" ? "text-emerald-700" : "text-amber-700";
  return (
    <span className={`text-sm font-medium ${tone}`} role="status">
      {status}
    </span>
  );
}

export function Field({
  label,
  detail,
  children,
}: {
  label: string;
  detail?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <label className="block space-y-1.5" htmlFor={id}>
      <span className="block text-sm font-medium">{label}</span>
      {detail && <span className="block text-sm text-muted">{detail}</span>}
      {isValidElement(children)
        ? cloneElement(children as ReactElement<{ id?: string }>, { id })
        : children}
    </label>
  );
}
