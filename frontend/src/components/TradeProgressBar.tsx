"use client";

import React from "react";
import { formatUsd } from "@/lib/utils";
import { Target, ShieldAlert, Zap, TrendingUp, AlertTriangle } from "lucide-react";

interface TradeProgressBarProps {
  entryPrice: number;
  currentPrice: number;
  tpPrice: number;
  slPrice: number;
  direction?: "BULLISH" | "BEARISH" | "LONG" | "SHORT" | string;
  targetProgressPct?: number;
}

export default function TradeProgressBar({
  entryPrice,
  currentPrice,
  tpPrice,
  slPrice,
  direction = "BULLISH",
  targetProgressPct,
}: TradeProgressBarProps) {
  const isLong = direction === "BULLISH" || direction === "LONG";

  // Calculate live progress if not passed directly
  let progress = targetProgressPct;
  if (progress === undefined || progress === null) {
    if (isLong) {
      if (currentPrice >= entryPrice) {
        const tpSpan = Math.max(1e-8, tpPrice - entryPrice);
        progress = Math.min(100, Math.max(0, ((currentPrice - entryPrice) / tpSpan) * 100));
      } else {
        const slSpan = Math.max(1e-8, entryPrice - slPrice);
        progress = -Math.min(100, Math.max(0, ((entryPrice - currentPrice) / slSpan) * 100));
      }
    } else {
      if (currentPrice <= entryPrice) {
        const tpSpan = Math.max(1e-8, entryPrice - tpPrice);
        progress = Math.min(100, Math.max(0, ((entryPrice - currentPrice) / tpSpan) * 100));
      } else {
        const slSpan = Math.max(1e-8, slPrice - entryPrice);
        progress = -Math.min(100, Math.max(0, ((currentPrice - entryPrice) / slSpan) * 100));
      }
    }
  }

  const isProfit = progress >= 0;
  const absProgress = Math.min(100, Math.max(0, Math.abs(progress)));

  // Distance remaining to TP and SL
  const distToTp = Math.abs(tpPrice - currentPrice);
  const distToSl = Math.abs(currentPrice - slPrice);
  const distToTpPct = entryPrice > 0 ? (distToTp / entryPrice) * 100 : 0;
  const distToSlPct = entryPrice > 0 ? (distToSl / entryPrice) * 100 : 0;

  // Visual width capped for smooth aesthetics
  const fillWidth = `${Math.max(3, (absProgress / 100) * 50)}%`;

  return (
    <div className="mt-3 w-full rounded-xl bg-dark-950/90 p-3 border border-slate-800/80 shadow-inner">
      {/* Header with Live Status & Metric */}
      <div className="flex items-center justify-between text-[11px] font-mono mb-2">
        <div className="flex items-center gap-1.5">
          {isProfit ? (
            <span className="flex items-center gap-1 text-emerald-400 font-bold bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-800/60">
              <TrendingUp className="h-3 w-3 animate-pulse" />
              IN PROFIT: +{absProgress.toFixed(1)}% to TP
            </span>
          ) : (
            <span className="flex items-center gap-1 text-rose-400 font-bold bg-rose-950/60 px-2 py-0.5 rounded border border-rose-800/60">
              <AlertTriangle className="h-3 w-3 animate-bounce" />
              IN LOSS: {absProgress.toFixed(1)}% to SL
            </span>
          )}
        </div>

        <div className="text-[10px] text-slate-400 flex items-center gap-2">
          {isProfit ? (
            <span className="text-emerald-300">
              Target Gap: <strong className="text-white">{formatUsd(distToTp)}</strong> ({distToTpPct.toFixed(2)}%)
            </span>
          ) : (
            <span className="text-rose-300">
              Buffer to SL: <strong className="text-white">{formatUsd(distToSl)}</strong> ({distToSlPct.toFixed(2)}%)
            </span>
          )}
        </div>
      </div>

      {/* Bi-Directional Dual-Bar Track */}
      {/* Left side: [SL 0%] ====== [Entry 50%] ====== [TP 100%] Right side */}
      <div className="relative h-3.5 w-full rounded-full bg-slate-900 border border-slate-700/80 overflow-hidden flex shadow-inner">
        {/* Left Half (Entry -> SL Danger Zone) */}
        <div className="relative w-1/2 h-full flex justify-end items-center bg-dark-950/60">
          {!isProfit && (
            <div
              className="h-full bg-gradient-to-l from-amber-500 via-rose-500 to-rose-600 rounded-l-full transition-all duration-300 shadow-lg shadow-rose-500/40 animate-pulse"
              style={{ width: `${Math.min(100, Math.max(4, absProgress))}%` }}
            />
          )}
        </div>

        {/* Center Divider / Entry Anchor Notch */}
        <div className="absolute left-1/2 top-0 bottom-0 -translate-x-1/2 w-1 bg-white shadow-[0_0_8px_rgba(255,255,255,0.9)] z-20 rounded-full" />

        {/* Right Half (Entry -> TP Profit Zone) */}
        <div className="relative w-1/2 h-full flex justify-start items-center bg-dark-950/60">
          {isProfit && (
            <div
              className="h-full bg-gradient-to-r from-cyan-400 via-emerald-400 to-emerald-500 rounded-r-full transition-all duration-300 shadow-lg shadow-emerald-500/40"
              style={{ width: `${Math.min(100, Math.max(4, absProgress))}%` }}
            />
          )}
        </div>
      </div>

      {/* Axis Pins & Price Labels */}
      <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-slate-400">
        {/* SL Pin */}
        <div className="flex flex-col items-start">
          <span className="flex items-center gap-0.5 text-rose-400 font-bold uppercase tracking-wider text-[9px]">
            <ShieldAlert className="h-2.5 w-2.5" /> Stop-Loss
          </span>
          <span className="text-slate-300 font-bold">{formatUsd(slPrice)}</span>
        </div>

        {/* Entry Pin (Center) */}
        <div className="flex flex-col items-center -translate-x-1">
          <span className="flex items-center gap-0.5 text-cyan-300 font-bold uppercase tracking-wider text-[9px]">
            <Zap className="h-2.5 w-2.5" /> Buy / Entry
          </span>
          <span className="text-white font-bold bg-dark-900 px-1.5 py-0.2 rounded border border-slate-700">
            {formatUsd(entryPrice)}
          </span>
        </div>

        {/* TP Pin */}
        <div className="flex flex-col items-end">
          <span className="flex items-center gap-0.5 text-emerald-400 font-bold uppercase tracking-wider text-[9px]">
            <Target className="h-2.5 w-2.5" /> Take-Profit
          </span>
          <span className="text-slate-300 font-bold">{formatUsd(tpPrice)}</span>
        </div>
      </div>
    </div>
  );
}
