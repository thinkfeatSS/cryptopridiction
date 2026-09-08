"use client";

import React, { useState, useEffect } from "react";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { formatTimeRemaining } from "@/lib/utils";

interface ScanCountdownBadgeProps {
  showShield?: boolean;
  className?: string;
}

export default React.memo(function ScanCountdownBadge({
  showShield = true,
  className = "",
}: ScanCountdownBadgeProps) {
  const { data: status } = useStatusQuery();
  const [localSeconds, setLocalSeconds] = useState<number>(0);

  useEffect(() => {
    if (status?.seconds_to_next_scan !== undefined) {
      setLocalSeconds(status.seconds_to_next_scan);
    }
  }, [status?.seconds_to_next_scan]);

  useEffect(() => {
    const timer = setInterval(() => {
      setLocalSeconds((prev) => (prev > 0 ? prev - 1 : 900));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className={`flex items-center gap-2.5 rounded-xl border border-cyan-500/40 bg-cyan-950/40 px-3.5 py-2 text-xs shadow-lg shadow-cyan-500/10 ${className}`}>
      <div className="relative flex h-3 w-3">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400 opacity-75"></span>
        <span className="relative inline-flex h-3 w-3 rounded-full bg-cyan-500"></span>
      </div>
      <div className="flex flex-col">
        <span className="text-[10px] uppercase font-bold tracking-wider text-cyan-300">
          Next AI Scan & Refresh In
        </span>
        <span className="font-mono text-sm font-black text-white">
          {formatTimeRemaining(localSeconds)}
        </span>
      </div>
    </div>
  );
});
