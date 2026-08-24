import type { ButtonHTMLAttributes, Ref } from "react";

import { cn } from "../../lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  ref?: Ref<HTMLButtonElement>;
  variant?: "default" | "outline" | "ghost" | "danger";
  loading?: boolean;
  loadingLabel?: string;
};

export function Button({
  ref,
  className,
  variant = "default",
  loading = false,
  loadingLabel = "Working…",
  children,
  disabled,
  ...props
}: ButtonProps) {
  const variants = {
    default: "bg-primary text-primary-foreground hover:bg-slate-700",
    outline: "border bg-panel hover:bg-slate-50",
    ghost: "hover:bg-slate-100",
    danger: "bg-danger text-white hover:opacity-90",
  };
  return (
    <button
      className={cn(
        "inline-flex min-h-9 items-center justify-center rounded-md px-3 text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        className,
      )}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      type="button"
      ref={ref}
      {...props}
    >
      {loading ? loadingLabel : children}
    </button>
  );
}
