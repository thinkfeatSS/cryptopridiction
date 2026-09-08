"use client";

import React, { useState, useEffect } from "react";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { formatTimeRemaining } from "@/lib/utils";
import { Radio } from "lucide-react";

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
      setLocalSeconds((prev) => (prev > 0 ? prev - 1 : 900));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="hidden lg:flex items-center gap-2 rounded-lg border border-indigo-500/30 bg-indigo-950/40 px-3 py-1.5 text-xs shadow-sm shadow-indigo-500/10">
      <Radio className="h-3.5 w-3.5 animate-pulse text-indigo-400 shrink-0" />
      <div className="flex flex-col">
        <span className="text-[9px] uppercase tracking-wider text-indigo-300/80 font-bold">
          Next 15M Scan In
        </span>
        <span className="font-mono text-xs font-bold text-white">
          {formatTimeRemaining(localSeconds)}
        </span>
      </div>
    </div>
  );
});
