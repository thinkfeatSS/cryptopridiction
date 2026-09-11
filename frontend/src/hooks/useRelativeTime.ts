"use client";

import { useState, useEffect } from "react";

export function formatRelativeMinutes(timestampStrOrMs: string | number | undefined | null): string {
  if (!timestampStrOrMs) return "Just now";
  try {
    const predictionTime =
      typeof timestampStrOrMs === "string"
        ? new Date(timestampStrOrMs).getTime()
        : timestampStrOrMs < 1e11
        ? timestampStrOrMs * 1000
        : timestampStrOrMs;

    if (isNaN(predictionTime)) return "Live";
    const now = Date.now();
    const diffSec = Math.floor((now - predictionTime) / 1000);
    if (diffSec < 45) return "Just now";
    const diffMinutes = Math.floor(diffSec / 60);
    if (diffMinutes === 1) return "1m ago";
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    const hours = Math.floor(diffMinutes / 60);
    const remMins = diffMinutes % 60;
    return `${hours}h ${remMins}m ago`;
  } catch {
    return "Live";
  }
}

export function formatServerPredictionTime(timestampStrOrMs: string | number | undefined | null): string {
  if (!timestampStrOrMs) return "Server Sync: Active";
  try {
    const d =
      typeof timestampStrOrMs === "string"
        ? new Date(timestampStrOrMs)
        : new Date(timestampStrOrMs < 1e11 ? timestampStrOrMs * 1000 : timestampStrOrMs);

    if (isNaN(d.getTime())) return "Live";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " UTC";
  } catch {
    return "Live";
  }
}

export function useRelativeTime(timestampStrOrMs?: string | number | null): string {
  const [text, setText] = useState<string>(() => formatRelativeMinutes(timestampStrOrMs));

  useEffect(() => {
    setText(formatRelativeMinutes(timestampStrOrMs));
    const interval = setInterval(() => {
      setText(formatRelativeMinutes(timestampStrOrMs));
    }, 10000); // Ticks every 10 seconds without full-component remount
    return () => clearInterval(interval);
  }, [timestampStrOrMs]);

  return text;
}
