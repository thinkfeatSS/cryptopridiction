"use client";

import React, { useState, useEffect } from "react";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { formatTimeRemaining } from "@/lib/utils";
import { Radio, Loader2 } from "lucide-react";

export default React.memo(function NavCountdownTimer() {
  const { data: status } = useStatusQuery();
  const [localSeconds, setLocalSeconds] = useState<number>(0);

  useEffect(() => {
    if (status?.seconds_to_next_scan !== undefined) {
      setLocalSeconds(status.seconds_to_next_scan);
    }
  }, [status?.seconds_to_next_scan]);

  useEffect(() => {
    const timer = setInterval(() => {
      setLocalSeconds((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const isScanning = Boolean(status?.is_scanning || localSeconds <= 0);

  return (
    <div
      className={`hidden lg:flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs shadow-sm transition-all ${
        isScanning
          ? "border-cyan-500/60 bg-cyan-950/60 text-cyan-300 shadow-cyan-500/20 animate-pulse"
          : "border-indigo-500/30 bg-indigo-950/40 text-indigo-300 shadow-indigo-500/10"
      }`}
    >
      {isScanning ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400 shrink-0" />
      ) : (
        <Radio className="h-3.5 w-3.5 animate-pulse text-indigo-400 shrink-0" />
      )}
      <div className="flex flex-col">
        <span
          className={`text-[9px] uppercase tracking-wider font-bold ${
            isScanning ? "text-cyan-300" : "text-indigo-300/80"
          }`}
        >
          {isScanning ? "AI Engine Status" : "Next 15M Scan In"}
        </span>
        <span className="font-mono text-xs font-bold text-white">
          {isScanning ? "⚡ Scanning 100 Coins..." : formatTimeRemaining(localSeconds)}
        </span>
      </div>
    </div>
  );
});
