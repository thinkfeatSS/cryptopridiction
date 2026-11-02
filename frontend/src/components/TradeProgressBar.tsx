"use client";

import React from "react";
import { formatUsd } from "@/lib/utils";
import {
  Target,
  ShieldAlert,
  Zap,
  TrendingUp,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Flame,
} from "lucide-react";

export interface TradeProgressBarProps {
  entryPrice: number;
  currentPrice: number;
  tpPrice?: number;
  slPrice: number;
  direction?: "BULLISH" | "BEARISH" | "LONG" | "SHORT" | string;
  targetProgressPct?: number;
  targetLabel?: string;
  tp1Price?: number;
  tp2Price?: number;
  tp3Price?: number;
  exitPrice?: number;
  peakPriceSeen?: number;
  troughPriceSeen?: number;
  isLimitPending?: boolean;
  isSlAtBreakeven?: boolean;
  livePnlPct?: number | null;
  status?: string;
  outcomeLabel?: string;
}

export default function TradeProgressBar({
  entryPrice,
  currentPrice,
  tpPrice,
  slPrice,
  direction = "BULLISH",
  targetProgressPct,
  targetLabel,
  tp1Price,
  tp2Price,
  tp3Price,
  exitPrice,
  peakPriceSeen,
  troughPriceSeen,
  isLimitPending = false,
  isSlAtBreakeven = false,
  livePnlPct,
  status = "ACTIVE",
  outcomeLabel = "",
}: TradeProgressBarProps) {
  const dirUpper = String(direction || "").toUpperCase();
  const isLong =
    dirUpper === "BULLISH" || dirUpper === "LONG" || dirUpper === "BUY";

  // Sanitize numeric inputs
  const entry = Math.max(0, Number(entryPrice) || 0);
  const sl = Math.max(0, Number(slPrice) || 0);
  const tp1 = Math.max(0, Number(tp1Price ?? tpPrice ?? entry));
  const tp2 = Math.max(0, Number(tp2Price ?? tp1));
  const tp3 = Math.max(0, Number(tp3Price ?? tp2));

  // Resolved statuses & outcome labels
  const stUpper = String(status || "").toUpperCase();
  const outUpper = String(outcomeLabel || "").toUpperCase();
  const combined = `${stUpper} ${outUpper}`;

  const isWonTp3 = combined.includes("TP3") && (combined.includes("WON") || combined.includes("HIT"));
  const isWonTp2 = !isWonTp3 && combined.includes("TP2") && (combined.includes("WON") || combined.includes("HIT"));
  const isWonTp1 = !isWonTp3 && !isWonTp2 && (combined.includes("TP1") || combined.includes("WON") || combined.includes("TARGET HIT"));
  const isWon = isWonTp3 || isWonTp2 || isWonTp1 || combined.includes("WON") || combined.includes("TARGET HIT");

  const isLost = combined.includes("LOST") || combined.includes("STOP");
  const isBreakevenClosed =
    !isWon &&
    !isLost &&
    (combined.includes("BREAKEVEN") ||
      combined.includes("BE_HIT") ||
      combined.includes("TIER0") ||
      combined.includes("GUARD") ||
      (combined.includes("EXPIRED") && combined.includes("BE")));

  const isResolved =
    isWon || isLost || isBreakevenClosed || combined.includes("EXPIRED") || combined.includes("CLOSED");

  // Effective price resolution:
  // If trade is resolved with an exit price, use exit_price.
  // Otherwise use currentPrice if > 0, fallback to entry.
  let effectivePrice = Number(currentPrice) || entry;
  if (isResolved && Number(exitPrice) > 0) {
    effectivePrice = Number(exitPrice);
  }

  // Determine active target and multi-target progress
  let activeTp = tp1;
  let activeTargetLabel = targetLabel || "TP1";
  let isTp1Passed = isWonTp1 || isWonTp2 || isWonTp3;
  let isTp2Passed = isWonTp2 || isWonTp3;

  if (isWonTp3) {
    activeTp = tp3;
    activeTargetLabel = "TP3";
  } else if (isWonTp2) {
    activeTp = tp2;
    activeTargetLabel = "TP2";
  } else if (isWonTp1) {
    activeTp = tp1;
    activeTargetLabel = "TP1";
  } else if (isLong) {
    if (tp2 > tp1 && effectivePrice >= tp1) {
      isTp1Passed = true;
      if (tp3 > tp2 && effectivePrice >= tp2) {
        isTp2Passed = true;
        activeTp = tp3;
        activeTargetLabel = "TP3";
      } else {
        activeTp = tp2;
        activeTargetLabel = "TP2";
      }
    } else {
      activeTp = tp1;
      activeTargetLabel = targetLabel || "TP1";
    }
  } else {
    // For Short: lower price = profit
    if (tp2 > 0 && tp2 < tp1 && effectivePrice <= tp1) {
      isTp1Passed = true;
      if (tp3 > 0 && tp3 < tp2 && effectivePrice <= tp2) {
        isTp2Passed = true;
        activeTp = tp3;
        activeTargetLabel = "TP3";
      } else {
        activeTp = tp2;
        activeTargetLabel = "TP2";
      }
    } else {
      activeTp = tp1;
      activeTargetLabel = targetLabel || "TP1";
    }
  }

  // Favorable directional price move
  const directionalDiff = isLong ? effectivePrice - entry : entry - effectivePrice;
  const isFavorable = directionalDiff > 0;
  const isAtEntry =
    !isResolved &&
    !isLimitPending &&
    entry > 0 &&
    Math.abs(directionalDiff) < 1e-6;

  // Floating or Realized PnL percentage calculation
  const computedLivePnlPct =
    livePnlPct !== undefined && livePnlPct !== null
      ? Number(livePnlPct)
      : entry > 0
      ? (directionalDiff / entry) * 100
      : 0;

  // Calculate live progress percentage toward active target or stop-loss
  let progressPct: number;
  let isProfitState: boolean;

  if (targetProgressPct !== undefined && targetProgressPct !== null) {
    progressPct = Number(targetProgressPct);
    isProfitState = progressPct >= 0;
  } else if (isWon) {
    isProfitState = true;
    progressPct = 100;
  } else if (isLost) {
    isProfitState = false;
    progressPct = -100;
  } else if (isBreakevenClosed) {
    isProfitState = computedLivePnlPct >= 0;
    progressPct = 0;
  } else {
    isProfitState = isFavorable;
    if (isFavorable) {
      const tpSpan = isLong
        ? Math.max(1e-8, activeTp - entry)
        : Math.max(1e-8, entry - activeTp);
      progressPct = Math.min(100, Math.max(0, (directionalDiff / tpSpan) * 100));
    } else {
      const slSpan = isLong
        ? Math.max(1e-8, entry - sl)
        : Math.max(1e-8, sl - entry);
      const adverseMove = Math.abs(directionalDiff);
      progressPct = -Math.min(100, Math.max(0, (adverseMove / slSpan) * 100));
    }
  }

  const absProgress = Math.min(100, Math.max(0, Math.abs(progressPct)));

  // Distance remaining to active TP and SL
  const distToTp = Math.abs(activeTp - effectivePrice);
  const distToSl = Math.abs(effectivePrice - sl);
  const distToTpPct = entry > 0 ? (distToTp / entry) * 100 : 0;
  const distToSlPct = entry > 0 ? (distToSl / entry) * 100 : 0;

  // Resting Limit Order Distance
  const distToLimit = Math.abs(entry - effectivePrice);
  const distToLimitPct = entry > 0 ? (distToLimit / entry) * 100 : 0;

  // Cursor percent mapping on bi-directional dual-track:
  // Center entry point is at 50%
  // Profit bar fills from 50% toward 100% (right)
  // Loss bar fills from 50% toward 0% (left)
  let cursorPercent = 50;
  if (isLimitPending) {
    cursorPercent = isLong ? 68 : 32;
  } else if (isWon) {
    cursorPercent = isWonTp3 ? 96 : isWonTp2 ? 86 : 76;
  } else if (isLost) {
    cursorPercent = 5;
  } else if (isBreakevenClosed || isAtEntry) {
    cursorPercent = 50;
  } else if (isProfitState) {
    cursorPercent = 50 + (absProgress / 100) * 45;
  } else {
    cursorPercent = 50 - (absProgress / 100) * 45;
  }
  cursorPercent = Math.min(96, Math.max(4, cursorPercent));

  // High-Watermark Peak Excursion Pin calculation
  let peakMarkerPercent: number | null = null;
  const tp1Span = isLong ? Math.max(1e-8, tp1 - entry) : Math.max(1e-8, entry - tp1);

  if (isLong && Number(peakPriceSeen) > entry && tp1Span > 0) {
    const peakDiff = Number(peakPriceSeen) - entry;
    if (peakDiff > directionalDiff) {
      const peakProg = Math.min(100, Math.max(0, (peakDiff / tp1Span) * 100));
      peakMarkerPercent = Math.min(96, Math.max(52, 50 + (peakProg / 100) * 45));
    }
  } else if (!isLong && Number(troughPriceSeen) > 0 && Number(troughPriceSeen) < entry && tp1Span > 0) {
    const troughDiff = entry - Number(troughPriceSeen);
    if (troughDiff > directionalDiff) {
      const troughProg = Math.min(100, Math.max(0, (troughDiff / tp1Span) * 100));
      peakMarkerPercent = Math.min(96, Math.max(52, 50 + (troughProg / 100) * 45));
    }
  }

  return (
    <div className="mt-3.5 w-full rounded-2xl bg-dark-950/95 p-3 sm:p-3.5 border border-slate-800/90 shadow-xl backdrop-blur-md">
      {/* 1. Header with Live Status & Metric Gaps */}
      <div className="flex items-center justify-between text-[11px] font-mono mb-2.5 flex-wrap gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          {isLimitPending ? (
            <span className="flex items-center gap-1.5 text-amber-300 font-black bg-amber-950/80 px-2.5 py-1 rounded-lg border border-amber-500/60 shadow-sm shadow-amber-500/20">
              <Clock className="h-3.5 w-3.5 animate-pulse text-amber-400" />
              <span>AWAITING ENTRY RETEST</span>
            </span>
          ) : isWon ? (
            <span className="flex items-center gap-1.5 text-emerald-300 font-black bg-emerald-950/90 px-2.5 py-1 rounded-lg border border-emerald-500/70 shadow-sm shadow-emerald-500/30">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              <span>TARGET HIT ({activeTargetLabel} SECURED)</span>
            </span>
          ) : isLost ? (
            <span className="flex items-center gap-1.5 text-rose-300 font-black bg-rose-950/90 px-2.5 py-1 rounded-lg border border-rose-500/70 shadow-sm shadow-rose-500/30">
              <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
              <span>STOP-LOSS TRIGGERED</span>
            </span>
          ) : isBreakevenClosed ? (
            <span className="flex items-center gap-1.5 text-cyan-300 font-black bg-cyan-950/90 px-2.5 py-1 rounded-lg border border-cyan-500/70 shadow-sm shadow-cyan-500/30">
              <ShieldAlert className="h-3.5 w-3.5 text-cyan-400" />
              <span>CLOSED AT BREAKEVEN (0.0% LOSS)</span>
            </span>
          ) : isAtEntry ? (
            <span className="flex items-center gap-1.5 text-cyan-300 font-black bg-cyan-950/70 px-2.5 py-1 rounded-lg border border-cyan-500/50 shadow-sm shadow-cyan-500/20">
              <Zap className="h-3.5 w-3.5 text-cyan-400 animate-pulse" />
              <span>AT ENTRY: +0.00% (IN-FLIGHT)</span>
            </span>
          ) : isProfitState ? (
            <span className="flex items-center gap-1.5 text-emerald-300 font-black bg-emerald-950/80 px-2.5 py-1 rounded-lg border border-emerald-500/60 shadow-sm shadow-emerald-500/20">
              <TrendingUp className="h-3.5 w-3.5 animate-pulse text-emerald-400" />
              <span>
                IN PROFIT: +{absProgress.toFixed(1)}% to {activeTargetLabel}
              </span>
              {isTp1Passed && (
                <span className="text-[9px] bg-emerald-900/90 text-emerald-200 px-1.5 py-0.2 rounded border border-emerald-400/60 font-black">
                  TP1 ✓
                </span>
              )}
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-rose-300 font-black bg-rose-950/80 px-2.5 py-1 rounded-lg border border-rose-500/60 shadow-sm shadow-rose-500/20">
              <AlertTriangle className="h-3.5 w-3.5 animate-bounce text-rose-400" />
              <span>IN DRAWDOWN: {absProgress.toFixed(1)}% to SL</span>
            </span>
          )}

          {/* Floating or Realized PnL Pill */}
          {!isLimitPending && (
            <span
              className={`px-2 py-0.5 rounded-md font-mono text-[10px] font-black border ${
                computedLivePnlPct >= 0
                  ? "bg-emerald-950/90 text-emerald-300 border-emerald-500/50"
                  : "bg-rose-950/90 text-rose-300 border-rose-500/50"
              }`}
            >
              {computedLivePnlPct >= 0 ? "+" : ""}
              {computedLivePnlPct.toFixed(2)}%
            </span>
          )}
        </div>

        {/* Dynamic Metric: Target Gap or Buffer */}
        <div className="text-[10px] text-slate-300 flex items-center gap-2">
          {isLimitPending ? (
            <span className="text-amber-300/90 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-800/40">
              Retest Gap:{" "}
              <strong className="text-white font-bold">{formatUsd(distToLimit)}</strong>{" "}
              ({distToLimitPct.toFixed(2)}%)
            </span>
          ) : isWon ? (
            <span className="text-emerald-300 bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-600/40 font-bold">
              ✓ Target Reached: {formatUsd(activeTp)}
            </span>
          ) : isLost ? (
            <span className="text-rose-300 bg-rose-950/50 px-2 py-0.5 rounded border border-rose-600/40 font-bold">
              Exit at Stop: {formatUsd(sl)}
            </span>
          ) : isProfitState || isAtEntry ? (
            <span className="text-emerald-300/90 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-800/40">
              Target Gap:{" "}
              <strong className="text-white font-bold">{formatUsd(distToTp)}</strong>{" "}
              ({distToTpPct.toFixed(2)}% to {activeTargetLabel})
            </span>
          ) : (
            <span className="text-rose-300/90 bg-rose-950/40 px-2 py-0.5 rounded border border-rose-800/40">
              Buffer to SL:{" "}
              <strong className="text-white font-bold">{formatUsd(distToSl)}</strong>{" "}
              ({distToSlPct.toFixed(2)}% cushion)
            </span>
          )}
        </div>
      </div>

      {/* 2. Bi-Directional Dual-Bar Track */}
      {/* Left side: [SL 0%] ====== [Entry 50%] ====== [TP 100%] Right side */}
      <div className="relative mt-2 mb-2 h-4 w-full rounded-full bg-slate-900/90 border border-slate-700/80 overflow-visible flex shadow-inner">
        {/* Left Half (Entry -> SL Danger Zone) */}
        <div className="relative w-1/2 h-full flex justify-end items-center bg-dark-950/80 rounded-l-full overflow-hidden border-r border-slate-800">
          {(isLost || (!isProfitState && !isAtEntry && !isLimitPending)) && (
            <div
              className={`h-full bg-gradient-to-l from-amber-500 via-rose-500 to-rose-600 rounded-l-full transition-all duration-300 shadow-md shadow-rose-500/40 ${
                isLost ? "w-full" : "animate-pulse"
              }`}
              style={{ width: isLost ? "100%" : `${Math.min(100, Math.max(3, absProgress))}%` }}
            />
          )}
        </div>

        {/* Center Divider / Entry Anchor Notch */}
        <div
          className={`absolute left-1/2 top-0 bottom-0 -translate-x-1/2 w-1.5 z-20 rounded-full transition-all ${
            isAtEntry || isBreakevenClosed
              ? "bg-cyan-300 shadow-[0_0_12px_rgba(34,211,238,1)]"
              : "bg-white shadow-[0_0_8px_rgba(255,255,255,0.9)]"
          }`}
          title={`Entry Anchor: ${formatUsd(entry)}`}
        />

        {/* Right Half (Entry -> TP Profit Zone) */}
        <div className="relative w-1/2 h-full flex justify-start items-center bg-dark-950/80 rounded-r-full overflow-hidden">
          {(isWon || (isProfitState && !isAtEntry && !isLimitPending)) && (
            <div
              className="h-full bg-gradient-to-r from-cyan-400 via-emerald-400 to-emerald-500 rounded-r-full transition-all duration-300 shadow-md shadow-emerald-500/40"
              style={{ width: isWon ? "100%" : `${Math.min(100, Math.max(3, absProgress))}%` }}
            />
          )}

          {/* TP1 Threshold Notch */}
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-slate-500/50 z-10"
            style={{ left: "55%" }}
            title={`TP1 Level: ${formatUsd(tp1)}`}
          />

          {/* TP2 Step Marker Pin */}
          {tp2 > 0 && Math.abs(tp2 - entry) > Math.abs(tp1 - entry) && (
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-slate-400/60 z-10"
              style={{ left: "75%" }}
              title={`TP2 Level: ${formatUsd(tp2)}`}
            />
          )}

          {/* TP3 Step Marker Pin */}
          {tp3 > 0 && Math.abs(tp3 - entry) > Math.abs(tp2 - entry) && (
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-slate-300/70 z-10"
              style={{ left: "92%" }}
              title={`TP3 Level: ${formatUsd(tp3)}`}
            />
          )}
        </div>

        {/* High-Watermark Ghost Pin (Highest Excursion) */}
        {peakMarkerPercent !== null && (
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 z-25 pointer-events-none"
            style={{ left: `${peakMarkerPercent}%` }}
            title={`Peak Excursion: ${formatUsd(isLong ? Number(peakPriceSeen) : Number(troughPriceSeen))}`}
          >
            <div className="flex flex-col items-center">
              <span className="h-2 w-2 rotate-45 bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.9)] opacity-80" />
            </div>
          </div>
        )}

        {/* Live Current Price Pin Cursor (Glowing Beacon Marker) */}
        <div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 z-30 transition-all duration-500 pointer-events-none"
          style={{ left: `${cursorPercent}%` }}
        >
          <div className="relative flex items-center justify-center">
            {/* Pulsing Beacon Halo */}
            <span
              className={`absolute h-5 w-5 rounded-full animate-ping opacity-75 ${
                isLimitPending
                  ? "bg-amber-400"
                  : isWon
                  ? "bg-emerald-400"
                  : isLost
                  ? "bg-rose-400"
                  : isAtEntry || isBreakevenClosed
                  ? "bg-cyan-400"
                  : isProfitState
                  ? "bg-emerald-400"
                  : "bg-rose-400"
              }`}
            />
            {/* Core Beacon Ring */}
            <span
              className={`relative h-4 w-4 rounded-full border-2 border-white shadow-md flex items-center justify-center ${
                isLimitPending
                  ? "bg-amber-500"
                  : isWon
                  ? "bg-emerald-500"
                  : isLost
                  ? "bg-rose-500"
                  : isAtEntry || isBreakevenClosed
                  ? "bg-cyan-500"
                  : isProfitState
                  ? "bg-emerald-500"
                  : "bg-rose-500"
              }`}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-white" />
            </span>
          </div>
        </div>
      </div>

      {/* 3. Non-Overlapping Responsive Axis Pins & Price Labels */}
      <div className="mt-2.5 grid grid-cols-3 gap-1 text-[10px] font-mono text-slate-400">
        {/* Left Column: Stop-Loss / Breakeven */}
        <div className="flex flex-col items-start min-w-0">
          <span
            className={`flex items-center gap-0.5 font-bold uppercase tracking-wider text-[9px] truncate ${
              isSlAtBreakeven ? "text-cyan-400" : "text-rose-400"
            }`}
          >
            <ShieldAlert className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">{isSlAtBreakeven ? "Breakeven" : "Stop-Loss"}</span>
          </span>
          <span
            className={`font-black truncate ${
              isSlAtBreakeven ? "text-cyan-300" : "text-rose-300"
            }`}
          >
            {formatUsd(sl)}
          </span>
        </div>

        {/* Center Column: Entry Price & Live Tag */}
        <div className="flex flex-col items-center min-w-0 text-center">
          <span className="flex items-center gap-0.5 text-cyan-300 font-bold uppercase tracking-wider text-[9px] truncate">
            <Zap className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">{isLong ? "Buy Entry" : "Sell Entry"}</span>
          </span>
          <div className="flex flex-col items-center gap-0.5">
            <span className="text-white font-black bg-dark-900 px-1.5 py-0.2 rounded border border-slate-700">
              {formatUsd(entry)}
            </span>
            <span
              className={`text-[9px] font-bold px-1 py-0.2 rounded ${
                isWon || isProfitState
                  ? "text-emerald-400 bg-emerald-950/60"
                  : isAtEntry || isBreakevenClosed
                  ? "text-cyan-300 bg-cyan-950/60"
                  : "text-rose-400 bg-rose-950/60"
              }`}
              title="Effective price"
            >
              {isResolved && exitPrice ? "Exit" : "Live"}: {formatUsd(effectivePrice)}
            </span>
          </div>
        </div>

        {/* Right Column: Take-Profit Milestones */}
        <div className="flex flex-col items-end min-w-0 text-right">
          <span className="flex items-center gap-0.5 text-emerald-400 font-bold uppercase tracking-wider text-[9px] truncate">
            <Target className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">{activeTargetLabel} Target</span>
          </span>
          <div className="flex flex-col items-end gap-0.5">
            <span className="text-emerald-300 font-black">{formatUsd(activeTp)}</span>
            {tp2 > 0 && Math.abs(tp2 - entry) > Math.abs(tp1 - entry) && (
              <span
                className="text-[9px] text-slate-500 font-normal truncate"
                title={`TP2: ${formatUsd(tp2)} | TP3: ${formatUsd(tp3)}`}
              >
                TP2: {formatUsd(tp2)}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
