"use client";

import React, { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { Zap, CheckCircle2, RefreshCw } from "lucide-react";

export default function AutoScanWatcher() {
  const queryClient = useQueryClient();
  const { data: status } = useStatusQuery();
  const lastVersionRef = useRef<number | null>(null);
  const lastScanTimestampRef = useRef<string | null>(null);
  const [showSyncBadge, setShowSyncBadge] = useState<boolean>(false);
  const [syncMessage, setSyncMessage] = useState<string>("");

  useEffect(() => {
    if (!status) return;

    const currentVersion = status.scan_version;
    const currentTimestamp = status.last_scan_timestamp;

    // Initial load setup
    if (lastVersionRef.current === null && currentVersion !== undefined) {
      lastVersionRef.current = currentVersion ?? null;
      lastScanTimestampRef.current = currentTimestamp || null;
      return;
    }

    // Detect if a new scan has completed & data stored in DB / files
    const versionChanged = currentVersion !== undefined && lastVersionRef.current !== null && currentVersion !== lastVersionRef.current;
    const timestampChanged = currentTimestamp && lastScanTimestampRef.current && currentTimestamp !== lastScanTimestampRef.current;

    if (versionChanged || timestampChanged) {
      console.log(`[AUTO-SYNC ⚡] New Scan Detected (v${currentVersion} at ${currentTimestamp}). Auto-refreshing all frontend tables & metrics...`);
      
      lastVersionRef.current = currentVersion ?? null;
      lastScanTimestampRef.current = currentTimestamp || null;

      // Invalidate all query caches immediately for full real-time reload
      queryClient.invalidateQueries({ queryKey: ["forecast"] });
      queryClient.invalidateQueries({ queryKey: ["signals"] });
      queryClient.invalidateQueries({ queryKey: ["kpi"] });
      queryClient.invalidateQueries({ queryKey: ["dailySummary"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["coinSignals"] });

      // Trigger visual toast confirmation
      setSyncMessage(`New AI Scan Completed • Data Auto-Refreshed`);
      setShowSyncBadge(true);
      const timer = setTimeout(() => {
        setShowSyncBadge(false);
      }, 4500);

      return () => clearTimeout(timer);
    }
  }, [status?.scan_version, status?.last_scan_timestamp, queryClient]);

  if (!showSyncBadge) return null;

  return (
    <div className="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 rounded-xl bg-cyan-950/90 px-4 py-2.5 text-xs font-bold text-cyan-300 border border-cyan-500/60 shadow-xl shadow-cyan-500/20 backdrop-blur-md animate-in slide-in-from-bottom-5 fade-in duration-300">
      <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-400">
        <Zap className="h-3.5 w-3.5 animate-bounce" />
      </span>
      <div className="flex flex-col">
        <span className="text-white font-black">{syncMessage}</span>
        <span className="text-[10px] text-cyan-400 font-mono">
          All 100 Assets & 8 Horizons Synchronized with DB
        </span>
      </div>
      <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 ml-1" />
    </div>
  );
}
