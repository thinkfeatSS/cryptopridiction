"use client";

import React, { useState, useEffect } from "react";
import { useNotificationCenter } from "@/context/NotificationContext";
import {
  X,
  Zap,
  TrendingUp,
  TrendingDown,
  Target,
  ShieldAlert,
  ShieldCheck,
  Clock,
  ExternalLink,
  Volume2,
  Flame,
  AlertTriangle,
} from "lucide-react";
import { formatUsd } from "@/lib/utils";

interface NotificationToasterProps {
  onSelectCoin?: (symbol: string) => void;
}

export default function NotificationToaster({ onSelectCoin }: NotificationToasterProps) {
  const { activeToast, dismissActiveToast, replaySound } = useNotificationCenter();
  const [progress, setProgress] = useState<number>(100);
  const [isPaused, setIsPaused] = useState<boolean>(false);

  useEffect(() => {
    if (!activeToast || isPaused) return;

    setProgress(100);
    const durationMs = 12000;
    const intervalMs = 100;
    const decrement = (intervalMs / durationMs) * 100;

    const timer = setInterval(() => {
      setProgress((prev) => {
        if (prev <= 0) {
          dismissActiveToast();
          return 100;
        }
        return Math.max(0, prev - decrement);
      });
    }, intervalMs);

    return () => clearInterval(timer);
  }, [activeToast, isPaused]);

  if (!activeToast) return null;

  const { type, symbol, horizon, direction, entryPrice, targetPrice, realizedPnlPct, conviction, grade } = activeToast;
  const isShort = direction === "SHORT" || direction === "BEARISH";

  const isHypeSurge = type === "HYPE_SURGE";
  const isBlowoffTop = type === "BLOWOFF_TOP";
  const isTpHit = type === "TP_HIT";
  const isSlHit = type === "SL_HIT";
  const isBreakeven = type === "BREAKEVEN_PROTECTED";
  const isExpired = type === "EXPIRED";

  const handleFocus = () => {
    if (onSelectCoin) {
      onSelectCoin(symbol);
    } else {
      const cleanSym = symbol.replace("/", "_");
      const cardEl = document.getElementById(`signal-card-${cleanSym}`);
      const rowEl = document.getElementById(`asset-row-${cleanSym}`);
      const targetEl = cardEl || rowEl;
      if (targetEl) {
        targetEl.scrollIntoView({ behavior: "smooth", block: "center" });
        targetEl.classList.add("ring-2", "ring-cyan-400", "shadow-lg", "shadow-cyan-500/25");
        setTimeout(() => {
          targetEl.classList.remove("ring-2", "ring-cyan-400", "shadow-lg", "shadow-cyan-500/25");
        }, 3000);
      }
    }
  };

  // Card background and border theme styling based on signal category
  const getCardThemeClass = () => {
    if (isHypeSurge) {
      return "bg-gradient-to-br from-amber-950/95 via-stone-900/95 to-orange-950/95 border-amber-500/60 shadow-amber-500/25 text-white ring-2 ring-amber-500/40";
    }
    if (isBlowoffTop) {
      return "bg-gradient-to-br from-rose-950/95 via-stone-900/95 to-red-950/95 border-rose-500/60 shadow-rose-500/25 text-white ring-2 ring-rose-500/40";
    }
    if (isTpHit) {
      return "bg-gradient-to-br from-emerald-950/95 via-stone-900/95 to-teal-950/90 border-emerald-500/50 shadow-emerald-500/20 text-white ring-2 ring-emerald-500/30";
    }
    if (isSlHit) {
      return "bg-gradient-to-br from-red-950/95 via-stone-900/95 to-amber-950/90 border-red-500/50 shadow-red-500/20 text-white ring-2 ring-red-500/30";
    }
    if (isBreakeven) {
      return "bg-gradient-to-br from-blue-950/95 via-stone-900/95 to-slate-900/95 border-blue-500/50 shadow-blue-500/20 text-white ring-2 ring-blue-500/30";
    }
    if (isShort) {
      return "bg-gradient-to-br from-red-950/90 via-stone-900/95 to-zinc-950/95 border-red-500/40 shadow-red-500/20 text-white ring-1 ring-red-500/30";
    }
    return "bg-gradient-to-br from-emerald-950/90 via-stone-900/95 to-zinc-950/95 border-emerald-500/40 shadow-emerald-500/20 text-white ring-1 ring-emerald-500/30";
  };

  const getProgressColorClass = () => {
    if (isHypeSurge) return "bg-amber-400";
    if (isBlowoffTop) return "bg-rose-500";
    if (isTpHit) return "bg-emerald-400";
    if (isSlHit) return "bg-red-500";
    if (isBreakeven) return "bg-blue-400";
    return isShort ? "bg-red-400" : "bg-emerald-400";
  };

  return (
    <div
      className="fixed bottom-6 right-6 z-50 max-w-md w-full animate-in fade-in slide-in-from-bottom-5 duration-300 pointer-events-auto"
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
    >
      <div className={`relative rounded-2xl p-5 border shadow-2xl backdrop-blur-xl transition-all duration-300 ${getCardThemeClass()}`}>
        {/* Top Header Badge */}
        <div className="flex items-center justify-between pb-3 border-b border-white/10">
          <div className="flex items-center gap-2">
            {isHypeSurge ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-amber-500/20 text-amber-300 border border-amber-500/50 animate-pulse">
                <Flame className="w-3.5 h-3.5 text-amber-400" />
                🔥 SUDDEN HYPE PUMP
              </span>
            ) : isBlowoffTop ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-rose-500/20 text-rose-300 border border-rose-500/50 animate-pulse">
                <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                🛑 SUDDEN BLOW-OFF TOP
              </span>
            ) : isTpHit ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 animate-pulse">
                <Target className="w-3.5 h-3.5 text-emerald-400" />
                🎯 TAKE-PROFIT HIT
              </span>
            ) : isSlHit ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-red-500/20 text-red-300 border border-red-500/40">
                <ShieldAlert className="w-3.5 h-3.5 text-red-400" />
                🛑 STOP-LOSS HIT
              </span>
            ) : isBreakeven ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-blue-500/20 text-blue-300 border border-blue-500/40">
                <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
                🛡️ BREAKEVEN PROTECTED
              </span>
            ) : isExpired ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-amber-500/20 text-amber-300 border border-amber-500/40">
                <Clock className="w-3.5 h-3.5 text-amber-400" />
                ⏱️ TIMEFRAME EXPIRED
              </span>
            ) : isShort ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-red-500/20 text-red-300 border border-red-500/40">
                <TrendingDown className="w-3.5 h-3.5 text-red-400" />
                🔴 NEW SHORT SIGNAL
              </span>
            ) : (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-black tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                🟢 NEW LONG SIGNAL
              </span>
            )}

            <span className="text-[11px] text-zinc-400 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {activeToast.timestamp}
            </span>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={() => replaySound(type)}
              title="Replay Alert Sound"
              className="p-1.5 rounded-lg bg-white/5 hover:bg-white/15 text-zinc-300 hover:text-white transition-colors"
            >
              <Volume2 className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={dismissActiveToast}
              title="Dismiss"
              className="p-1.5 rounded-lg bg-white/5 hover:bg-white/20 text-zinc-400 hover:text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="mt-3.5">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-xl font-black tracking-tight text-white">{symbol}</h3>
                <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-white/10 text-zinc-300 uppercase">
                  {horizon}
                </span>
                {grade && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                    {grade}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5 mt-1">
                {isShort ? (
                  <span className="text-red-400 font-extrabold text-sm flex items-center gap-1">
                    <TrendingDown className="w-4 h-4" />
                    🔴 SHORT / FADE
                  </span>
                ) : (
                  <span className="text-emerald-400 font-extrabold text-sm flex items-center gap-1">
                    <TrendingUp className="w-4 h-4" />
                    🟢 LONG BUY
                  </span>
                )}
              </div>
            </div>

            <div className="text-right">
              <div className="text-[11px] uppercase tracking-wider text-zinc-400">
                {realizedPnlPct !== undefined ? "Realized Return" : "Target Gain"}
              </div>
              <div
                className={`text-lg font-black ${
                  (realizedPnlPct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {realizedPnlPct !== undefined
                  ? `${realizedPnlPct >= 0 ? "+" : ""}${realizedPnlPct.toFixed(2)}%`
                  : "+2.50%"}
              </div>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-3 gap-2 mt-3 p-2 rounded-xl bg-black/40 border border-white/5 text-xs">
            {entryPrice !== undefined && entryPrice > 0 && (
              <div>
                <span className="text-[9px] uppercase tracking-wider text-zinc-400 block">Entry</span>
                <span className="font-mono font-bold text-white text-xs">{formatUsd(entryPrice)}</span>
              </div>
            )}
            {targetPrice !== undefined && targetPrice > 0 && (
              <div>
                <span className="text-[9px] uppercase tracking-wider text-zinc-400 block">Target (TP)</span>
                <span className="font-mono font-bold text-emerald-300 text-xs">{formatUsd(targetPrice)}</span>
              </div>
            )}
            {conviction !== undefined && (
              <div>
                <span className="text-[9px] uppercase tracking-wider text-zinc-400 block">Conviction</span>
                <span className="font-mono font-bold text-cyan-300 text-xs">{conviction.toFixed(1)}%</span>
              </div>
            )}
          </div>

          <p className="mt-2.5 text-xs text-zinc-300 leading-relaxed line-clamp-2">
            {activeToast.message}
          </p>
        </div>

        {/* Footer Actions */}
        <div className="mt-3.5 flex items-center justify-between gap-2 pt-2 border-t border-white/10">
          <span className="text-[11px] text-zinc-400 font-mono">Live Displayed Signal Alert</span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleFocus}
              className="px-3 py-1.5 rounded-lg bg-cyan-600/80 hover:bg-cyan-500 text-white text-xs font-bold transition-colors flex items-center gap-1 shadow-lg shadow-cyan-600/30"
            >
              Inspect Signal <ExternalLink className="w-3 h-3" />
            </button>
            <button
              onClick={dismissActiveToast}
              className="px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-zinc-300 text-xs font-semibold transition-colors"
            >
              Close
            </button>
          </div>
        </div>

        {/* Countdown Progress Bar */}
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/40 rounded-b-2xl overflow-hidden">
          <div
            className={`h-full transition-all duration-100 ease-linear ${getProgressColorClass()}`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </div>
  );
}

