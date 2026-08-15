import type { SelectHTMLAttributes } from "react";

import { cn } from "../../lib/utils";

export function Select({
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 w-full rounded-md border bg-panel px-2 text-sm",
        className,
      )}
      {...props}
    />
  );
}
