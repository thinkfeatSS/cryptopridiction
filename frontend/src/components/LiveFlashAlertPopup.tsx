"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  X,
  Zap,
  TrendingUp,
  TrendingDown,
  Volume2,
  VolumeX,
  Bell,
  Clock,
  ExternalLink,
  ChevronRight,
  ShieldAlert,
  Sparkles,
  Flame,
  AlertTriangle,
  Layers,
} from "lucide-react";
import { formatUsd } from "@/lib/utils";
import { playSignalChime, playParabolicBreakoutAlert, playExhaustionSellAlert } from "@/lib/audioAlert";

export interface FlashAlertItem {
  id: string;
  timestamp: string;
  symbol: string;
  direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH";
  horizon: string;
  entryPrice: number;
  targetPrice: number;
  targetGainPct: number;
  bestSellPrice: number;
  stopLossPrice: number;
  conviction: number;
  metaWinProb: number;
  grade: string;
  decision: string;
  isBlowoffTop?: boolean;
  isHypeSurge?: boolean;
  alertType: "BLOWOFF_TOP" | "HYPE_BREAKOUT" | "ELITE_SIGNAL";
}

interface LiveFlashAlertPopupProps {
  topSignals: any[];
  soundEnabled: boolean;
  onToggleSound: () => void;
  onSelectCoin?: (symbol: string) => void;
}

export default function LiveFlashAlertPopup({
  topSignals,
  soundEnabled,
  onToggleSound,
  onSelectCoin,
}: LiveFlashAlertPopupProps) {
  const [activeAlerts, setActiveAlerts] = useState<FlashAlertItem[]>([]);
  const [alertHistory, setAlertHistory] = useState<FlashAlertItem[]>([]);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);
  const [currentAlertIndex, setCurrentAlertIndex] = useState<number>(0);
  const [progress, setProgress] = useState<number>(100);
  const [isPaused, setIsPaused] = useState<boolean>(false);

  const prevSignalsRef = useRef<string>("");
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Convert raw signal to normalized FlashAlertItem
  const normalizeSignal = (s: any): FlashAlertItem => {
    const rawDir = (s.direction || "LONG").toUpperCase();
    const isShort = rawDir.includes("SHORT") || rawDir.includes("BEAR");
    const isBlowoff =
      Boolean(s.is_blowoff_top) ||
      s.decision?.includes("BLOW-OFF") ||
      s.decision?.includes("EXHAUSTION");
    const isHype =
      Boolean(s.is_hype_surge) ||
      s.decision?.includes("HYPE") ||
      s.decision?.includes("PARABOLIC");

    const entry = Number(s.entry_price || s.current_price || 0);
    const target = Number(s.predicted_next_price || s.tp1_price || s.target_price || s.tp_price || (isShort ? entry * 0.92 : entry * 1.05));
    const targetGain =
      s.predicted_return_pct !== undefined
        ? Number(s.predicted_return_pct)
        : s.expected_return_pct !== undefined
        ? Number(s.expected_return_pct)
        : entry > 0 && target > 0
        ? ((target - entry) / entry) * 100
        : isShort
        ? -8.0
        : 8.0;

    const bestSell = Number(
      s.best_sell_price ||
      s.tp3_price ||
      (isShort ? (isBlowoff ? entry * 0.90 : entry * 0.95) : (isHype ? entry * 1.10 : entry * 1.05))
    );

    const stopLoss = Number(s.sl_price || (isShort ? entry * 1.03 : entry * 0.97));
    const conviction = Number(s.conviction_pct || s.conviction || 75.0);
    const metaWin = Number(s.meta_win_prob_pct || (s.meta_win_prob ? s.meta_win_prob * 100 : 70.0));

    let alertType: "BLOWOFF_TOP" | "HYPE_BREAKOUT" | "ELITE_SIGNAL" = "ELITE_SIGNAL";
    if (isBlowoff) alertType = "BLOWOFF_TOP";
    else if (isHype) alertType = "HYPE_BREAKOUT";

    const id = `${s.symbol || "UNKNOWN"}-${s.horizon || s.horizon_tag || "SCALP"}-${Math.round(entry * 1000)}`;

    return {
      id,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      symbol: s.symbol || "UNKNOWN",
      direction: isShort ? "SHORT" : "LONG",
      horizon: s.horizon_tag || s.horizon || s.horizon_name || "15M Scalp",
      entryPrice: entry,
      targetPrice: target,
      targetGainPct: targetGain,
      bestSellPrice: bestSell,
      stopLossPrice: stopLoss,
      conviction,
      metaWinProb: metaWin,
      grade: s.grade || s.quality_grade || (conviction >= 75 ? "💎 Grade A+" : "🟢 Grade A"),
      decision: s.decision || (isBlowoff ? "🛑 Blow-Off Top Exhaustion Sell" : isHype ? "🚀 Parabolic Momentum Breakout" : "🎯 Elite Confluence Setup"),
      isBlowoffTop: isBlowoff,
      isHypeSurge: isHype,
      alertType,
    };
  };

  // Detect new signals on signal stream change
  useEffect(() => {
    if (!topSignals || topSignals.length === 0) return;

    const signalFingerprint = topSignals
      .map((s) => `${s.symbol}-${s.direction}-${s.entry_price || s.current_price}-${s.decision}`)
      .join("|");

    if (prevSignalsRef.current && prevSignalsRef.current !== signalFingerprint) {
      // Find newly arrived signals
      const newItems = topSignals.map(normalizeSignal);
      if (newItems.length > 0) {
        setActiveAlerts(newItems);
        setCurrentAlertIndex(0);
        setProgress(100);

        // Append to history without duplicates
        setAlertHistory((prev) => {
          const combined = [...newItems, ...prev];
          const uniqueMap = new Map<string, FlashAlertItem>();
          for (const it of combined) {
            if (!uniqueMap.has(it.id)) {
              uniqueMap.set(it.id, it);
            }
          }
          return Array.from(uniqueMap.values()).slice(0, 15);
        });
      }
    } else if (!prevSignalsRef.current && topSignals.length > 0) {
      // Initial load: populate history
      const initialItems = topSignals.map(normalizeSignal);
      setAlertHistory(initialItems.slice(0, 10));
    }

    prevSignalsRef.current = signalFingerprint;
  }, [topSignals]);

  // Auto-dismiss timer progress (15 seconds per alert)
  useEffect(() => {
    if (activeAlerts.length === 0 || isPaused) return;

    const durationMs = 16000;
    const intervalMs = 100;
    const decrement = (intervalMs / durationMs) * 100;

    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev <= 0) {
          handleDismissCurrent();
          return 100;
        }
        return Math.max(0, prev - decrement);
      });
    }, intervalMs);

    return () => clearInterval(interval);
  }, [activeAlerts, isPaused, currentAlertIndex]);

  const handleDismissCurrent = () => {
    if (activeAlerts.length <= 1) {
      setActiveAlerts([]);
      setCurrentAlertIndex(0);
    } else {
      setActiveAlerts((prev) => prev.filter((_, idx) => idx !== currentAlertIndex));
      setCurrentAlertIndex(0);
      setProgress(100);
    }
  };

  const handleDismissAll = () => {
    setActiveAlerts([]);
    setCurrentAlertIndex(0);
  };

  const handleReplayCurrentSound = (item: FlashAlertItem) => {
    if (item.alertType === "BLOWOFF_TOP") {
      playExhaustionSellAlert(0.42);
    } else if (item.alertType === "HYPE_BREAKOUT") {
      playParabolicBreakoutAlert(0.40);
    } else {
      playSignalChime(0.30);
    }
  };

  const handleFocusCoin = (sym: string) => {
    if (onSelectCoin) {
      onSelectCoin(sym);
    } else {
      const el = document.getElementById(`asset-row-${sym.replace("/", "_")}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  };

  const currentAlert = activeAlerts[currentAlertIndex] || null;

  return (
    <>
      {/* 1. FLOATING FLASH ALERT TOAST POPUP */}
      {currentAlert && (
        <div
          className="fixed bottom-6 right-6 z-50 max-w-md w-full animate-in fade-in slide-in-from-bottom-5 duration-300 pointer-events-auto"
          onMouseEnter={() => setIsPaused(true)}
          onMouseLeave={() => setIsPaused(false)}
        >
          <div
            className={`relative rounded-2xl p-5 border shadow-2xl backdrop-blur-xl transition-all duration-300 ${
              currentAlert.alertType === "BLOWOFF_TOP"
                ? "bg-gradient-to-br from-red-950/95 via-stone-900/95 to-amber-950/90 border-red-500/50 shadow-red-500/20 text-white ring-2 ring-red-500/30"
                : currentAlert.alertType === "HYPE_BREAKOUT"
                ? "bg-gradient-to-br from-emerald-950/95 via-stone-900/95 to-teal-950/90 border-emerald-500/50 shadow-emerald-500/20 text-white ring-2 ring-emerald-500/30"
                : "bg-gradient-to-br from-cyan-950/95 via-stone-900/95 to-slate-900/95 border-cyan-500/50 shadow-cyan-500/20 text-white ring-2 ring-cyan-500/30"
            }`}
          >
            {/* Top Glowing Header Badge */}
            <div className="flex items-center justify-between pb-3 border-b border-white/10">
              <div className="flex items-center gap-2">
                {currentAlert.alertType === "BLOWOFF_TOP" ? (
                  <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-red-500/20 text-red-300 border border-red-500/40 animate-pulse">
                    <ShieldAlert className="w-3.5 h-3.5 text-red-400" />
                    🛑 BLOW-OFF TOP (SELL NOW)
                  </span>
                ) : currentAlert.alertType === "HYPE_BREAKOUT" ? (
                  <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 animate-pulse">
                    <Flame className="w-3.5 h-3.5 text-emerald-400" />
                    🚀 PARABOLIC HYPE PUMP
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                    <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
                    {currentAlert.grade}
                  </span>
                )}

                <span className="text-[11px] text-zinc-400 flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {currentAlert.timestamp}
                </span>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleReplayCurrentSound(currentAlert)}
                  title="Replay Alert Chime"
                  className="p-1.5 rounded-lg bg-white/5 hover:bg-white/15 text-zinc-300 hover:text-white transition-colors"
                >
                  <Volume2 className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={handleDismissCurrent}
                  title="Dismiss This Alert"
                  className="p-1.5 rounded-lg bg-white/5 hover:bg-white/20 text-zinc-400 hover:text-white transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Main Alert Body */}
            <div className="mt-3.5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-xl font-black tracking-tight text-white flex items-center gap-2">
                      {currentAlert.symbol}
                    </h3>
                    <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-white/10 text-zinc-300 uppercase">
                      {currentAlert.horizon}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    {currentAlert.direction === "LONG" ? (
                      <span className="text-emerald-400 font-extrabold text-sm flex items-center gap-1">
                        <TrendingUp className="w-4 h-4" />
                        🟢 LONG BUY EXECUTE
                      </span>
                    ) : (
                      <span className="text-red-400 font-extrabold text-sm flex items-center gap-1">
                        <TrendingDown className="w-4 h-4" />
                        🔴 SHORT / SELL FADE
                      </span>
                    )}
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-[11px] uppercase tracking-wider text-zinc-400">Target Profit</div>
                  <div
                    className={`text-lg font-black ${
                      currentAlert.targetGainPct >= 0 ? "text-emerald-400" : "text-amber-400"
                    }`}
                  >
                    {currentAlert.targetGainPct >= 0 ? `+${currentAlert.targetGainPct.toFixed(2)}%` : `${currentAlert.targetGainPct.toFixed(2)}%`}
                  </div>
                </div>
              </div>

              {/* Price Levels Grid */}
              <div className="grid grid-cols-4 gap-1.5 mt-3.5 p-2 rounded-xl bg-black/40 border border-white/5 text-xs">
                <div>
                  <span className="text-[9px] uppercase tracking-wider text-zinc-400 block">Entry</span>
                  <span className="font-mono font-bold text-white text-xs">{formatUsd(currentAlert.entryPrice)}</span>
                </div>
                <div>
                  <span className="text-[9px] uppercase tracking-wider text-zinc-400 block">
                    {currentAlert.direction === "SHORT" ? "Down TP" : "Target (TP1)"}
                  </span>
                  <span
                    className={`font-mono font-bold text-xs ${
                      currentAlert.direction === "SHORT" ? "text-amber-300" : "text-emerald-300"
                    }`}
                  >
                    {formatUsd(currentAlert.targetPrice)}
                  </span>
                </div>
                <div>
                  <span className="text-[9px] uppercase tracking-wider text-amber-400 font-bold block">Best Sell</span>
                  <span className="font-mono font-black text-amber-300 text-xs">{formatUsd(currentAlert.bestSellPrice)}</span>
                </div>
                <div>
                  <span className="text-[9px] uppercase tracking-wider text-zinc-400 block">SL</span>
                  <span className="font-mono font-bold text-red-400 text-xs">{formatUsd(currentAlert.stopLossPrice)}</span>
                </div>
              </div>

              {/* Conviction & Tactical Decision */}
              <div className="mt-2.5 flex items-center justify-between text-[11px] text-zinc-300">
                <span className="flex items-center gap-1">
                  🧠 AI Conviction: <b className="text-white">{currentAlert.conviction.toFixed(1)}%</b>
                </span>
                <span className="flex items-center gap-1">
                  🔮 Win Prob: <b className="text-cyan-300">{currentAlert.metaWinProb.toFixed(1)}%</b>
                </span>
              </div>

              <div className="mt-2 p-2 rounded-lg bg-white/5 border border-white/5 text-[11px] text-zinc-300 leading-snug line-clamp-2">
                {currentAlert.decision}
              </div>
            </div>

            {/* Bottom Actions */}
            <div className="mt-3.5 flex items-center justify-between gap-2 pt-2 border-t border-white/10">
              <div className="flex items-center gap-2">
                {activeAlerts.length > 1 && (
                  <span className="text-[11px] font-bold text-zinc-400 bg-white/10 px-2 py-0.5 rounded-full">
                    {currentAlertIndex + 1} of {activeAlerts.length}
                  </span>
                )}
                {activeAlerts.length > 1 && (
                  <button
                    onClick={() => setCurrentAlertIndex((prev) => (prev + 1) % activeAlerts.length)}
                    className="text-[11px] font-bold text-cyan-400 hover:text-cyan-300 underline"
                  >
                    Next Alert →
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleFocusCoin(currentAlert.symbol)}
                  className="px-3 py-1.5 rounded-lg bg-cyan-600/80 hover:bg-cyan-500 text-white text-xs font-bold transition-colors flex items-center gap-1 shadow-lg shadow-cyan-600/30"
                >
                  Inspect Matrix <ExternalLink className="w-3 h-3" />
                </button>
                <button
                  onClick={handleDismissAll}
                  className="px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-zinc-300 text-xs font-semibold transition-colors"
                >
                  Dismiss All
                </button>
              </div>
            </div>

            {/* Countdown Progress Bar */}
            <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/40 rounded-b-2xl overflow-hidden">
              <div
                className={`h-full transition-all duration-100 ease-linear ${
                  currentAlert.alertType === "BLOWOFF_TOP"
                    ? "bg-red-500"
                    : currentAlert.alertType === "HYPE_BREAKOUT"
                    ? "bg-emerald-400"
                    : "bg-cyan-400"
                }`}
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* 2. FLOATING FLASH ALERT HISTORY PILL (Bottom Left or Right Trigger) */}
      <div className="fixed bottom-6 left-6 z-40">
        <button
          onClick={() => setIsDrawerOpen(!isDrawerOpen)}
          className="group relative flex items-center gap-2.5 px-3.5 py-2.5 rounded-2xl bg-zinc-900/90 hover:bg-zinc-800 text-white border border-zinc-700/60 shadow-xl backdrop-blur-md transition-all hover:scale-105 active:scale-95"
        >
          <div className="relative">
            <Bell className="w-4 h-4 text-cyan-400 group-hover:rotate-12 transition-transform" />
            {alertHistory.length > 0 && (
              <span className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-cyan-500 text-black text-[10px] font-black flex items-center justify-center animate-pulse">
                {alertHistory.length}
              </span>
            )}
          </div>
          <span className="text-xs font-bold tracking-tight">Flash Signals History</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-zinc-400 font-mono">
            {alertHistory.length}
          </span>
        </button>
      </div>

      {/* 3. RECENT FLASH SIGNALS DRAWER MODAL */}
      {isDrawerOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="relative w-full max-w-2xl bg-zinc-950 border border-zinc-800 rounded-2xl p-6 shadow-2xl text-white max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between pb-4 border-b border-zinc-800">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                  <Zap className="w-5 h-5" />
                </div>
                <div>
                  <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
                    Live Flash Signals & Audio Chime History
                  </h2>
                  <p className="text-xs text-zinc-400">
                    Real-time volatile breakouts, blow-off tops, and Grade A+ signals audited during scans.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsDrawerOpen(false)}
                className="p-2 rounded-xl bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto mt-4 space-y-3 pr-1">
              {alertHistory.length === 0 ? (
                <div className="text-center py-12 text-zinc-500">
                  <Bell className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  <p className="text-sm font-semibold">No flash alerts triggered yet this session.</p>
                  <p className="text-xs text-zinc-600 mt-1">Alerts will automatically pop up when high-momentum coins or tops are found.</p>
                </div>
              ) : (
                alertHistory.map((item) => (
                  <div
                    key={item.id}
                    className={`p-4 rounded-xl border transition-all hover:border-zinc-700 bg-zinc-900/60 ${
                      item.alertType === "BLOWOFF_TOP"
                        ? "border-red-500/30 hover:bg-red-950/20"
                        : item.alertType === "HYPE_BREAKOUT"
                        ? "border-emerald-500/30 hover:bg-emerald-950/20"
                        : "border-zinc-800 hover:bg-zinc-900"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-black text-base text-white">{item.symbol}</span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-zinc-800 text-zinc-300 uppercase">
                            {item.horizon}
                          </span>
                          {item.alertType === "BLOWOFF_TOP" && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-black bg-red-500/20 text-red-300 border border-red-500/40">
                              🛑 BLOW-OFF TOP
                            </span>
                          )}
                          {item.alertType === "HYPE_BREAKOUT" && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                              🚀 HYPE BREAKOUT
                            </span>
                          )}
                          <span className="text-[10px] text-zinc-400 font-mono ml-auto">
                            {item.timestamp}
                          </span>
                        </div>

                        <div className="mt-2 flex items-center gap-3 text-xs font-mono flex-wrap">
                          <div>
                            <span className="text-[10px] text-zinc-500 block uppercase">Entry</span>
                            <span className="text-white font-bold">{formatUsd(item.entryPrice)}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-zinc-500 block uppercase">Target</span>
                            <span
                              className={`font-bold ${
                                item.direction === "SHORT" ? "text-amber-300" : "text-emerald-300"
                              }`}
                            >
                              {formatUsd(item.targetPrice)} ({item.targetGainPct >= 0 ? `+${item.targetGainPct.toFixed(1)}%` : `${item.targetGainPct.toFixed(1)}%`})
                            </span>
                          </div>
                          <div>
                            <span className="text-[10px] text-amber-400 block uppercase font-bold">Best Sell</span>
                            <span className="text-amber-300 font-bold">{formatUsd(item.bestSellPrice)}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-zinc-500 block uppercase">Stop Loss</span>
                            <span className="text-red-400 font-bold">{formatUsd(item.stopLossPrice)}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-zinc-500 block uppercase">Conviction</span>
                            <span className="text-cyan-300 font-bold">{item.conviction.toFixed(1)}%</span>
                          </div>
                        </div>

                        <p className="mt-2 text-xs text-zinc-300 leading-relaxed">{item.decision}</p>
                      </div>

                      <div className="flex flex-col items-end gap-2">
                        <button
                          onClick={() => handleReplayCurrentSound(item)}
                          className="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white transition-colors"
                          title="Play Sound"
                        >
                          <Volume2 className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => {
                            setIsDrawerOpen(false);
                            handleFocusCoin(item.symbol);
                          }}
                          className="px-2.5 py-1 rounded-lg bg-cyan-600/80 hover:bg-cyan-500 text-white text-xs font-bold transition-colors flex items-center gap-1"
                        >
                          Inspect <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Footer */}
            <div className="mt-4 pt-3 border-t border-zinc-800 flex items-center justify-between text-xs text-zinc-400">
              <span>Auto-refreshing on 60s multi-horizon market sweeps</span>
              <button
                onClick={() => setAlertHistory([])}
                className="hover:text-red-400 transition-colors font-medium"
              >
                Clear History
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
