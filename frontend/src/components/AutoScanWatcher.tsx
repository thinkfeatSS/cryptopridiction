"use client";

import React, { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { playSignalChime } from "@/lib/audioAlerts";
import { Zap, CheckCircle2 } from "lucide-react";

export default function AutoScanWatcher() {
  const queryClient = useQueryClient();
  const { data: status } = useStatusQuery();
  const lastFullScanVersionRef = useRef<number | null>(null);
  const lastPortfolioVersionRef = useRef<number | null>(null);
  const lastScanTimestampRef = useRef<string | null>(null);
  const lastAlertTimeRef = useRef<number>(0);
  const [showSyncBadge, setShowSyncBadge] = useState<boolean>(false);
  const [syncMessage, setSyncMessage] = useState<string>("");

  useEffect(() => {
    if (!status) return;

    const currentFullVersion = status.full_scan_version ?? status.scan_version;
    const currentPortfolioVersion = status.portfolio_version;
    const currentTimestamp = status.last_scan_timestamp;

    // 1. Initial load baseline setup
    if (lastFullScanVersionRef.current === null && currentFullVersion !== undefined) {
      lastFullScanVersionRef.current = currentFullVersion;
      lastPortfolioVersionRef.current = currentPortfolioVersion ?? 1;
      lastScanTimestampRef.current = currentTimestamp || null;
      lastAlertTimeRef.current = Date.now();
      return;
    }

    // 2. Full 100-Coin AI Scan Completed
    const isNewFullScan =
      (currentFullVersion !== undefined &&
        lastFullScanVersionRef.current !== null &&
        currentFullVersion > lastFullScanVersionRef.current) ||
      (currentTimestamp &&
        lastScanTimestampRef.current &&
        currentTimestamp !== lastScanTimestampRef.current);

    const now = Date.now();
    const cooldownElapsed = now - lastAlertTimeRef.current > 45000; // Minimum 45s cooldown between scan toasts

    if (isNewFullScan) {
      lastFullScanVersionRef.current = currentFullVersion ?? null;
      lastScanTimestampRef.current = currentTimestamp || null;
      lastPortfolioVersionRef.current = currentPortfolioVersion ?? null;

      // Invalidate all query caches for complete synchronization
      queryClient.invalidateQueries({ queryKey: ["forecast"] });
      queryClient.invalidateQueries({ queryKey: ["signals"] });
      queryClient.invalidateQueries({ queryKey: ["kpi"] });
      queryClient.invalidateQueries({ queryKey: ["dailySummary"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["coinSignals"] });

      if (cooldownElapsed) {
        lastAlertTimeRef.current = now;

        // Trigger Web Audio Alert Chime if sound is enabled
        try {
          const soundEnabled = localStorage.getItem("quantedge_sound_enabled") !== "false";
          if (soundEnabled) {
            playSignalChime();
          }
        } catch (e) {
          console.error(e);
        }

        // Display toast notification once per full scan
        setSyncMessage("New AI Scan Completed • Data Auto-Refreshed");
        setShowSyncBadge(true);
        const timer = setTimeout(() => {
          setShowSyncBadge(false);
        }, 4500);

        return () => clearTimeout(timer);
      }
    } else if (
      currentPortfolioVersion !== undefined &&
      lastPortfolioVersionRef.current !== null &&
      currentPortfolioVersion > lastPortfolioVersionRef.current
    ) {
      // 3. Silent background sync for intra-candle price ticks and paper trades
      lastPortfolioVersionRef.current = currentPortfolioVersion;
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["signals"] });
      queryClient.invalidateQueries({ queryKey: ["kpi"] });
    }
  }, [status?.full_scan_version, status?.scan_version, status?.portfolio_version, status?.last_scan_timestamp, queryClient]);

  if (!showSyncBadge) return null;

  return (
    <div className="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 rounded-xl bg-cyan-950/95 px-4 py-2.5 text-xs font-bold text-cyan-300 border border-cyan-500/60 shadow-xl shadow-cyan-500/20 backdrop-blur-md animate-in slide-in-from-bottom-5 fade-in duration-300">
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
