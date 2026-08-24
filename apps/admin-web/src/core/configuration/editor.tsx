import { useBlocker } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { Button } from "../../components/ui/button";
import {
  Field,
  ResourceStatus,
  type ResourceStatusValue,
  WorkspaceHeader,
} from "../ui/foundation";

export type ConfigurationStatus = ResourceStatusValue;

export function EditorActions({
  dirty,
  hasDraft,
  saving,
  publishing = false,
  validating = false,
  saveDisabled = false,
  remoteChanged = false,
  conflict = false,
  cleanStatus = "Published",
  title,
  description,
  onSave,
  onPublish,
  onReload,
}: {
  dirty: boolean;
  hasDraft: boolean;
  saving: boolean;
  publishing?: boolean;
  validating?: boolean;
  saveDisabled?: boolean;
  remoteChanged?: boolean;
  conflict?: boolean;
  cleanStatus?: ConfigurationStatus;
  title?: string;
  description?: string;
  onSave: () => Promise<void>;
  onPublish?: () => Promise<void>;
  onReload?: () => Promise<void>;
}) {
  const [navigationSave, setNavigationSave] = useState(false);
  const [validationSave, setValidationSave] = useState(false);
  const stayRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const blocker = useBlocker({
    shouldBlockFn: () => dirty,
    enableBeforeUnload: dirty,
    withResolver: true,
  });
  const status: ConfigurationStatus = saving
    ? "Saving…"
    : publishing
      ? "Publishing…"
      : dirty
        ? "Unsaved changes"
        : hasDraft
          ? "Saved · Pending publish"
          : cleanStatus;

  async function saveAndContinue() {
    setNavigationSave(true);
    try {
      await onSave();
      blocker.proceed?.();
    } finally {
      setNavigationSave(false);
    }
  }

  useEffect(() => {
    if (!validationSave || validating) return;
    setValidationSave(false);
    if (!saveDisabled) void onSave().catch(() => undefined);
  }, [onSave, saveDisabled, validating, validationSave]);

  useEffect(() => {
    if (blocker.status === "blocked") {
      previousFocus.current = document.activeElement as HTMLElement | null;
      requestAnimationFrame(() => stayRef.current?.focus());
      return;
    }
    previousFocus.current?.focus();
    previousFocus.current = null;
  }, [blocker.status]);

  useEffect(() => {
    if (blocker.status !== "blocked") return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        blocker.reset?.();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
      const buttons = dialog
        ? [...dialog.querySelectorAll<HTMLButtonElement>("button")].filter(
            (button) => !button.disabled,
          )
        : [];
      if (!buttons.length) return;
      const current = buttons.indexOf(
        document.activeElement as HTMLButtonElement,
      );
      const next = event.shiftKey
        ? buttons[current <= 0 ? buttons.length - 1 : current - 1]
        : buttons[current === buttons.length - 1 ? 0 : current + 1];
      event.preventDefault();
      next.focus();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [blocker.status, blocker.reset]);

  const requestSave = () => {
    if (validating) {
      setValidationSave(true);
      return;
    }
    void onSave().catch(() => undefined);
  };

  return (
    <>
      {(remoteChanged || conflict) && (
        <div
          aria-live="polite"
          className="mb-4 rounded-md border border-warning/30 bg-warning-soft p-4 text-sm"
          role="alert"
        >
          <p className="font-medium">
            {conflict
              ? "This configuration changed on the server."
              : "Remote configuration changed."}
          </p>
          <p className="mt-1 text-muted">
            Your unsaved changes were preserved.
          </p>
          {onReload && (
            <Button
              className="mt-3"
              onClick={() => void onReload().catch(() => undefined)}
              variant="outline"
            >
              Reload
            </Button>
          )}
        </div>
      )}
      {title ? (
        <WorkspaceHeader
          description={description}
          primaryAction={{
            label: "Save",
            disabled:
              !dirty ||
              saving ||
              publishing ||
              conflict ||
              validationSave ||
              (saveDisabled && !validating),
            loading: saving || validationSave,
            loadingLabel: saving ? "Saving…" : "Checking…",
            onClick: requestSave,
          }}
          status={status}
          title={title}
        />
      ) : (
        <div className="mb-7 flex flex-wrap items-center justify-between gap-3 border-b pb-4">
          <StatusBadge status={status} />
          <div className="flex gap-2">
            <Button
              disabled={
                !dirty ||
                saving ||
                publishing ||
                conflict ||
                validationSave ||
                (saveDisabled && !validating)
              }
              loading={saving || validationSave}
              loadingLabel={saving ? "Saving…" : "Checking…"}
              onClick={requestSave}
            >
              Save
            </Button>
            {onPublish && (
              <Button
                disabled={
                  dirty ||
                  !hasDraft ||
                  saving ||
                  publishing ||
                  conflict ||
                  remoteChanged
                }
                loading={publishing}
                loadingLabel="Publishing…"
                onClick={() => void onPublish().catch(() => undefined)}
                variant="outline"
              >
                Publish
              </Button>
            )}
          </div>
        </div>
      )}
      {validationSave && validating && (
        <p className="mb-4 text-sm text-muted" role="status">
          Validating latest changes…
        </p>
      )}
      {blocker.status === "blocked" && (
        <div
          aria-describedby="unsaved-description"
          aria-labelledby="unsaved-title"
          aria-modal="true"
          className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4"
          role="dialog"
        >
          <div className="w-full max-w-md rounded-lg bg-panel p-6 shadow-xl">
            <h2 className="text-lg font-semibold" id="unsaved-title">
              Unsaved changes
            </h2>
            <p className="mt-2 text-sm text-muted" id="unsaved-description">
              You have changes that have not been saved.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button
                ref={stayRef}
                onClick={() => blocker.reset?.()}
                variant="ghost"
              >
                Stay
              </Button>
              <Button onClick={() => blocker.proceed?.()} variant="outline">
                Discard changes
              </Button>
              <Button
                disabled={navigationSave || conflict}
                onClick={() => void saveAndContinue().catch(() => undefined)}
              >
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
  return <ResourceStatus status={status} />;
}

export { Field };
