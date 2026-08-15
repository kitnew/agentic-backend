import type { PropsWithChildren } from "react";

/** Browser authentication is enforced by the edge gateway; no API token enters JavaScript. */
export function AdminAuthBoundary({ children }: PropsWithChildren) {
  return <>{children}</>;
}
