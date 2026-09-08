"use client";

import React, { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AutoScanWatcher from "@/components/AutoScanWatcher";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5000,
            gcTime: 1000 * 60 * 10, // 10 minutes cache garbage collection
            refetchOnWindowFocus: false, // Prevents duplicate network spikes when switching tabs
            retry: 2,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AutoScanWatcher />
      {children}
    </QueryClientProvider>
  );
}
