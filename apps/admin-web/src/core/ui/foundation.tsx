import {
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
  useId,
  useState,
} from "react";

import { Button } from "../../components/ui/button";
import { Select } from "../../components/ui/select";
import { cn } from "../../lib/utils";

export type ResourceStatusValue =
  | "Published"
  | "Saved · Pending publish"
  | "Unsaved changes"
  | "Saving…"
  | "Publishing…"
  | "Conflict"
  | "Ready"
  | "Degraded"
  | "Not configured"
  | "Disabled"
  | "Saved";

const statusTone: Record<ResourceStatusValue, string> = {
  Published: "text-success",
  "Saved · Pending publish": "text-warning",
  "Unsaved changes": "text-warning",
  "Saving…": "text-muted",
  "Publishing…": "text-muted",
  Conflict: "text-danger",
  Ready: "text-success",
  Degraded: "text-danger",
  "Not configured": "text-muted",
  Disabled: "text-muted",
  Saved: "text-muted",
};

export function ResourceStatus({ status }: { status: ResourceStatusValue }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-sm font-medium",
        statusTone[status],
      )}
      data-status={status}
      role="status"
    >
      <span aria-hidden="true" className="text-[0.65rem]">
        ●
      </span>
      {status}
    </span>
  );
}

type WorkspaceAction = {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  loadingLabel?: string;
};

export function WorkspaceHeader({
  title,
  description,
  status,
  primaryAction,
  secondaryActions,
}: {
  title: string;
  description?: string;
  status?: ResourceStatusValue;
  primaryAction?: WorkspaceAction;
  secondaryActions?: ReactNode;
}) {
  const hasActionArea = Boolean(status || primaryAction || secondaryActions);
  return (
    <header className={cn(hasActionArea ? "mb-7 border-b pb-4" : "mb-6")}>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description && (
        <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>
      )}
      {hasActionArea && (
        <div className="mt-3 flex min-h-9 flex-wrap items-center justify-between gap-3">
          {status ? <ResourceStatus status={status} /> : <span />}
          {(primaryAction || secondaryActions) && (
            <div className="flex flex-wrap items-center gap-2">
              {secondaryActions}
              {primaryAction && (
                <Button
                  disabled={primaryAction.disabled}
                  loading={primaryAction.loading}
                  loadingLabel={primaryAction.loadingLabel}
                  onClick={primaryAction.onClick}
                >
                  {primaryAction.label}
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </header>
  );
}

export function FormSection({
  title,
  description,
  collapsible = true,
  expanded,
  defaultExpanded = true,
  onExpandedChange,
  headerActions,
  summary,
  children,
}: {
  title: string;
  description?: string;
  collapsible?: boolean;
  expanded?: boolean;
  defaultExpanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  headerActions?: ReactNode;
  summary?: ReactNode;
  children: ReactNode;
}) {
  const [localExpanded, setLocalExpanded] = useState(defaultExpanded);
  const isExpanded = collapsible ? (expanded ?? localExpanded) : true;
  const contentId = useId();
  const toggle = () => {
    if (!collapsible) return;
    const next = !isExpanded;
    if (expanded === undefined) setLocalExpanded(next);
    onExpandedChange?.(next);
  };

  return (
    <section className="border-b py-1">
      <div className="flex min-h-14 items-center gap-3">
        <button
          aria-controls={contentId}
          aria-expanded={isExpanded}
          className="flex min-w-0 flex-1 items-center gap-3 py-3 text-left disabled:cursor-default"
          disabled={!collapsible}
          onClick={toggle}
          type="button"
        >
          <span aria-hidden="true" className="w-3 text-xs text-muted">
            {collapsible ? (isExpanded ? "▾" : "▸") : ""}
          </span>
          <span className="min-w-0">
            <span className="block font-semibold">{title}</span>
            {description && (
              <span className="mt-0.5 block text-sm font-normal text-muted">
                {description}
              </span>
            )}
            {!isExpanded && summary && (
              <span className="mt-0.5 block text-sm font-normal text-muted">
                {summary}
              </span>
            )}
          </span>
        </button>
        {headerActions && <div className="shrink-0">{headerActions}</div>}
      </div>
      {isExpanded && (
        <div className="pb-6 pl-6" id={contentId}>
          {children}
        </div>
      )}
    </section>
  );
}

export function ToggleSection({
  enabled,
  onEnabledChange,
  enabledLabel = "Enabled",
  disabledLabel = "Disabled",
  disabledSummary = "Using Platform defaults",
  children,
  ...sectionProps
}: Omit<
  Parameters<typeof FormSection>[0],
  "children" | "headerActions" | "summary"
> & {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  enabledLabel?: string;
  disabledLabel?: string;
  disabledSummary?: ReactNode;
  children: ReactNode;
}) {
  return (
    <FormSection
      {...sectionProps}
      collapsible={enabled ? sectionProps.collapsible : false}
      expanded={enabled ? sectionProps.expanded : false}
      headerActions={
        <label className="inline-flex items-center gap-2 text-sm font-medium">
          <input
            checked={enabled}
            className="size-4 w-auto"
            onChange={(event) => onEnabledChange(event.target.checked)}
            type="checkbox"
          />
          {enabled ? enabledLabel : disabledLabel}
        </label>
      }
      summary={!enabled ? disabledSummary : undefined}
    >
      {enabled ? children : null}
    </FormSection>
  );
}

export function FormGrid({
  columns = 2,
  children,
  className,
}: {
  columns?: 1 | 2;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid gap-x-5 gap-y-4",
        columns === 2 && "sm:grid-cols-2",
        className,
      )}
      data-columns={columns}
    >
      {children}
    </div>
  );
}

export function Field({
  label,
  helperText,
  detail,
  error,
  fullWidth = false,
  children,
}: {
  label: string;
  helperText?: string;
  detail?: string;
  error?: string;
  fullWidth?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;
  const help = helperText ?? detail;
  const control = isValidElement(children)
    ? cloneElement(
        children as ReactElement<{
          id?: string;
          "aria-describedby"?: string;
          "aria-invalid"?: boolean;
        }>,
        {
          id,
          "aria-describedby":
            [help && helpId, error && errorId].filter(Boolean).join(" ") ||
            undefined,
          "aria-invalid": error ? true : undefined,
        },
      )
    : children;
  return (
    <div className={cn("min-w-0", fullWidth && "sm:col-span-2")}>
      <label className="block text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      {help && (
        <p className="mt-0.5 text-sm text-muted" id={helpId}>
          {help}
        </p>
      )}
      <div className="mt-1.5">{control}</div>
      {error && (
        <p className="mt-1 text-sm text-red-700" id={errorId} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function FieldGroup({
  label,
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <fieldset className="min-w-0 space-y-3">
      {label && <legend className="text-sm font-semibold">{label}</legend>}
      {children}
    </fieldset>
  );
}

export function FieldRow({ children }: { children: ReactNode }) {
  return <FormGrid>{children}</FormGrid>;
}

export function RepeatedList({
  addLabel = "Add",
  onAdd,
  children,
}: {
  addLabel?: string;
  onAdd: () => void;
  children: ReactNode;
}) {
  return (
    <div className="space-y-3">
      {children}
      <Button aria-label={addLabel} onClick={onAdd} variant="outline">
        + {addLabel}
      </Button>
    </div>
  );
}

export function RepeatedItem({
  title,
  onRemove,
  children,
}: {
  title: ReactNode;
  onRemove: () => void;
  children: ReactNode;
}) {
  const itemLabel = typeof title === "string" ? title : "item";
  return (
    <section className="space-y-4 rounded-md border p-4">
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-medium">{title}</h3>
        <Button
          aria-label={`Remove ${itemLabel}`}
          onClick={onRemove}
          variant="ghost"
        >
          Remove
        </Button>
      </div>
      {children}
    </section>
  );
}

export type KeyValueItem = { id: string; key: string; value: string };

export function KeyValueListEditor({
  items,
  onChange,
  addLabel = "Add",
}: {
  items: KeyValueItem[];
  onChange: (items: KeyValueItem[]) => void;
  addLabel?: string;
}) {
  return (
    <RepeatedList
      addLabel={addLabel}
      onAdd={() =>
        onChange([...items, { id: crypto.randomUUID(), key: "", value: "" }])
      }
    >
      {items.map((item, index) => (
        <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" key={item.id}>
          <Field label="Key">
            <input
              value={item.key}
              onChange={(event) =>
                onChange(
                  items.map((candidate, candidateIndex) =>
                    candidateIndex === index
                      ? { ...candidate, key: event.target.value }
                      : candidate,
                  ),
                )
              }
            />
          </Field>
          <Field label="Value">
            <input
              value={item.value}
              onChange={(event) =>
                onChange(
                  items.map((candidate, candidateIndex) =>
                    candidateIndex === index
                      ? { ...candidate, value: event.target.value }
                      : candidate,
                  ),
                )
              }
            />
          </Field>
          <Button
            aria-label={`Remove row ${index + 1}`}
            className="self-end"
            onClick={() =>
              onChange(items.filter((_, itemIndex) => itemIndex !== index))
            }
            variant="ghost"
          >
            Remove
          </Button>
        </div>
      ))}
    </RepeatedList>
  );
}

export function CodeEditor({
  label,
  value,
  onChange,
  error,
  readOnly = false,
  monospace = true,
  minHeight = 160,
  maxHeight,
}: {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  error?: string;
  readOnly?: boolean;
  monospace?: boolean;
  minHeight?: number;
  maxHeight?: number;
}) {
  return (
    <Field error={error} label={label}>
      <textarea
        className={cn(monospace && "font-mono")}
        readOnly={readOnly}
        style={{ minHeight, maxHeight }}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
      />
    </Field>
  );
}

export function TechnicalDiagnostics({
  children,
  title = "Technical diagnostics",
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <details className="border-t pt-4 text-sm text-muted">
      <summary className="cursor-pointer font-medium text-foreground">
        {title}
      </summary>
      <div className="mt-3 overflow-auto rounded-md bg-slate-100 p-3">
        {children}
      </div>
    </details>
  );
}

export type SelectorOption = { value: string; label: string };

export function Selector({
  label,
  value,
  onChange,
  options,
  loading = false,
  disabled = false,
  emptyLabel = "No options available",
  helperText,
  createAction,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectorOption[];
  loading?: boolean;
  disabled?: boolean;
  emptyLabel?: string;
  helperText?: string;
  createAction?: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Field helperText={helperText} label={label}>
        <Select
          disabled={disabled || loading || options.length === 0}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {loading ? (
            <option value="">Loading…</option>
          ) : options.length === 0 ? (
            <option value="">{emptyLabel}</option>
          ) : (
            options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))
          )}
        </Select>
      </Field>
      {createAction}
    </div>
  );
}

export const ProfileSelector = Selector;
export const IntegrationSelector = Selector;
export const ListSection = RepeatedList;
export const StructuredEditor = CodeEditor;
