"use client";

import React, { useState, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AutoScanWatcher from "@/components/AutoScanWatcher";
import { NotificationProvider } from "@/context/NotificationContext";
import NotificationToaster from "@/components/NotificationToaster";
import NotificationCenterDrawer from "@/components/NotificationCenterDrawer";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 3000,
            gcTime: 1000 * 60 * 10, // 10 minutes cache garbage collection
            refetchOnWindowFocus: true, // Automatically revalidates stale queries when user returns to tab
            refetchOnReconnect: true,
            retry: 2,
          },
        },
      })
  );

  useEffect(() => {
    // Proactively purge any rogue or legacy service workers and browser CacheStorage
    if (typeof window !== "undefined") {
      if ("serviceWorker" in navigator) {
        navigator.serviceWorker.getRegistrations().then((registrations) => {
          for (const reg of registrations) {
            reg.unregister().catch(() => {});
          }
        }).catch(() => {});
      }
      if ("caches" in window) {
        caches.keys().then((keys) => {
          for (const key of keys) {
            caches.delete(key).catch(() => {});
          }
        }).catch(() => {});
      }
    }
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <AutoScanWatcher />
      <NotificationProvider>
        {children}
        <NotificationToaster />
        <NotificationCenterDrawer />
      </NotificationProvider>
    </QueryClientProvider>
  );
}
