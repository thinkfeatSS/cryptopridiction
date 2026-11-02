"use client";

import React, { useState, useEffect } from "react";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { formatTimeRemaining } from "@/lib/utils";
import { Loader2, Zap } from "lucide-react";

interface ScanCountdownBadgeProps {
  showShield?: boolean;
  className?: string;
}

export default React.memo(function ScanCountdownBadge({
  showShield = true,
  className = "",
}: ScanCountdownBadgeProps) {
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
      className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2 text-xs shadow-lg transition-all ${
        isScanning
          ? "border-cyan-400/60 bg-cyan-950/70 shadow-cyan-500/20 animate-pulse"
          : "border-emerald-500/40 bg-emerald-950/40 shadow-emerald-500/10"
      } ${className}`}
    >
      <div className="relative flex h-3 w-3">
        {isScanning ? (
          <Loader2 className="h-3 w-3 animate-spin text-cyan-400" />
        ) : (
          <>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-500"></span>
          </>
        )}
      </div>
      <div className="flex flex-col">
        <span className="text-[10px] uppercase font-bold tracking-wider text-emerald-400">
          {isScanning ? "⚡ Retraining Fresh Models" : "⚡ 15M Candle Retrain"}
        </span>
        <span className="font-mono text-sm font-black text-white" suppressHydrationWarning>
          {isScanning
            ? (status?.scanned_assets_count ? `Retraining: ${status.scanned_assets_count}/${status?.total_assets_count || 110} Coins...` : "Retraining Universe Models...")
            : (!mounted ? "Candle Sync (60s)" : `Sync in ${formatTimeRemaining(localSeconds)}`)}
        </span>
      </div>
    </div>
  );
});
