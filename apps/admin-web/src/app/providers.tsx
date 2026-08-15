import { QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";

import { AdminAuthBoundary } from "../core/auth/boundary";
import { queryClient } from "./query-client";

export function AppProviders({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>
      <AdminAuthBoundary>{children}</AdminAuthBoundary>
    </QueryClientProvider>
  );
}
