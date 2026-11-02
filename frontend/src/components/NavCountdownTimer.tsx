"use client";

import React, { useState, useEffect } from "react";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { formatTimeRemaining } from "@/lib/utils";
import { Zap, Loader2 } from "lucide-react";

export default React.memo(function NavCountdownTimer() {
  const { data: status } = useStatusQuery();
  const [mounted, setMounted] = useState(false);
  
  // Calculate remaining seconds directly against the engine's authoritative next_scan_timestamp
  const getRemainingSeconds = React.useCallback(() => {
    if (status?.next_scan_timestamp && status.next_scan_timestamp > 0) {
      const nowSec = Math.floor(Date.now() / 1000);
      const diff = status.next_scan_timestamp - nowSec;
      if (diff > 0) return diff;
    }
    if (status?.seconds_to_next_scan !== undefined && status.seconds_to_next_scan > 0) {
      return status.seconds_to_next_scan;
    }
    return 60;
  }, [status?.next_scan_timestamp, status?.seconds_to_next_scan]);

  const [localSeconds, setLocalSeconds] = useState<number>(60);

  useEffect(() => {
    setMounted(true);
    setLocalSeconds(getRemainingSeconds());
  }, [getRemainingSeconds]);

  useEffect(() => {
    const timer = setInterval(() => {
      setLocalSeconds(getRemainingSeconds());
    }, 1000);
    return () => clearInterval(timer);
  }, [getRemainingSeconds]);

  const isScanning = Boolean(status?.is_scanning);

  return (
    <div
      title={status?.next_scan_utc ? `Candle Boundary Sync Target: ${status.next_scan_utc} UTC (Fresh Retrained Models)` : "Candle-Synchronized 15M Retraining Active"}
      className={`hidden lg:flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs shadow-sm transition-all ${
        isScanning
          ? "border-cyan-500/60 bg-cyan-950/60 text-cyan-300 shadow-cyan-500/20 animate-pulse"
          : "border-emerald-500/40 bg-emerald-950/30 text-emerald-300 shadow-emerald-500/10"
      }`}
    >
      {isScanning ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400 shrink-0" />
      ) : (
        <Zap className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
      )}
      <div className="flex flex-col">
        <span
          className={`text-[9px] uppercase tracking-wider font-bold ${
            isScanning ? "text-cyan-300" : "text-emerald-400/90"
          }`}
        >
          {isScanning ? "AI Retraining Models" : "⚡ 15M Candle Retrain"}
        </span>
        <span className="font-mono text-xs font-bold text-white" suppressHydrationWarning>
          {isScanning
            ? (status?.scanned_assets_count ? `Retraining: ${status.scanned_assets_count}/${status?.total_assets_count || 110} Coins...` : "Retraining Models...")
            : (!mounted ? "Candle Sync (60s)" : `Sync in ${formatTimeRemaining(localSeconds)}`)}
        </span>
      </div>
    </div>
  );
});
