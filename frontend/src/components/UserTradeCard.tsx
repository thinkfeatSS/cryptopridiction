"use client";

import React, { useMemo } from "react";
import { TrackedTrade } from "@/hooks/useTrackedTrades";
import { formatUsd } from "@/lib/utils";
import {
  ArrowUpRight,
  ArrowDownRight,
  Target,
  ShieldCheck,
  ShieldAlert,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  X,
  Sparkles,
} from "lucide-react";

interface UserTradeCardProps {
  trade: TrackedTrade;
  onCloseTrade: (id: string) => void;
  onRemoveTrade: (id: string) => void;
}

export default function UserTradeCard({
  trade,
  onCloseTrade,
  onRemoveTrade,
}: UserTradeCardProps) {
  const isLong = trade.direction === "LONG" || trade.direction === "BULLISH" || (trade as any).direction_label === "LONG";
  const isClosed = trade.status !== "ACTIVE";

  // Calculate live return
  const currentReturnPct = useMemo(() => {
    if (trade.realized_pnl_pct !== undefined && isClosed) {
      return trade.realized_pnl_pct;
    }
    if (trade.entry_price <= 0) return 0;
    const diff = trade.current_price - trade.entry_price;
    return isLong ? (diff / trade.entry_price) * 100 : (-diff / trade.entry_price) * 100;
  }, [trade, isLong, isClosed]);

  // Distance percentages to TP1 and SL
  const { distToTp1Pct, distToSlPct, progressPct } = useMemo(() => {
    const entry = trade.entry_price;
    const curr = trade.current_price;
    const tp1 = trade.tp1_price;
    const sl = trade.sl_price;

    if (entry <= 0 || tp1 === entry) return { distToTp1Pct: 0, distToSlPct: 0, progressPct: 50 };

    const totalRange = Math.abs(tp1 - sl);
    if (totalRange === 0) return { distToTp1Pct: 0, distToSlPct: 0, progressPct: 50 };

    let pPct = 50;
    if (isLong) {
      pPct = ((curr - sl) / totalRange) * 100;
    } else {
      pPct = ((sl - curr) / totalRange) * 100;
    }
    pPct = Math.max(0, Math.min(100, pPct));

    const toTp = Math.abs((tp1 - curr) / curr) * 100;
    const toSl = Math.abs((curr - sl) / curr) * 100;

    return { distToTp1Pct: toTp, distToSlPct: toSl, progressPct: pPct };
  }, [trade, isLong]);

  // Outcome status styling
  const isWon = trade.status.startsWith("WON");
  const isLost = trade.status.startsWith("LOST");
  const isBe = trade.status === "BREAKEVEN";

  return (
    <div
      className={`rounded-2xl p-4 sm:p-5 border transition-all duration-300 relative overflow-hidden ${
        isClosed
          ? isWon
            ? "bg-emerald-950/20 border-emerald-500/30"
            : isLost
            ? "bg-rose-950/20 border-rose-500/30"
            : "bg-slate-900/40 border-slate-800"
          : "bg-dark-900/90 border-slate-800 hover:border-cyan-500/40 shadow-xl"
      }`}
    >
      {/* Top Header: Symbol, Horizon, Grade, & Delete */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={`flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-black tracking-wide ${
              isLong
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                : "bg-rose-500/20 text-rose-400 border border-rose-500/40"
            }`}
          >
            {isLong ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
            {trade.direction}
          </span>

          <span className="text-base sm:text-lg font-black tracking-tight text-white font-mono">
            {trade.symbol}
          </span>

          <span className="text-xs text-cyan-400 font-sans font-medium">
            {trade.horizon}
          </span>

          <span className="rounded bg-dark-950 px-2 py-0.5 text-[11px] font-bold text-slate-300 border border-slate-800">
            {trade.quality_grade}
          </span>

          {trade.meta_win_prob_pct !== undefined && (
            <span className="text-[11px] text-purple-300 font-mono font-bold bg-purple-950/80 px-2 py-0.5 rounded border border-purple-800/50">
              🧠 {trade.meta_win_prob_pct.toFixed(1)}% Prob
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Status Badge */}
          <span
            className={`rounded-lg px-2.5 py-1 text-xs font-bold font-mono flex items-center gap-1.5 border ${
              isWon
                ? "bg-emerald-950 text-emerald-300 border-emerald-500"
                : isLost
                ? "bg-rose-950 text-rose-300 border-rose-500"
                : isBe
                ? "bg-cyan-950 text-cyan-300 border-cyan-500"
                : "bg-amber-950/80 text-amber-300 border-amber-500/50 animate-pulse"
            }`}
          >
            {!isClosed && <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />}
            {trade.outcome_label || (isClosed ? "CLOSED" : "IN FLIGHT ⏳")}
          </span>

          <button
            onClick={() => onRemoveTrade(trade.id)}
            className="p-1 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
            title="Remove from my tracked list"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Main Stats: Entry, Current Price, & Live Return */}
      <div className="mt-3.5 grid grid-cols-2 sm:grid-cols-4 gap-3 bg-dark-950/60 p-3 rounded-xl border border-slate-800/60">
        <div>
          <span className="text-[10px] text-slate-500 block uppercase font-mono">Entry Price</span>
          <span className="text-sm font-bold text-white font-mono">{formatUsd(trade.entry_price)}</span>
        </div>

        <div>
          <span className="text-[10px] text-slate-500 block uppercase font-mono">Current / Exit</span>
          <span className="text-sm font-bold text-cyan-300 font-mono">{formatUsd(trade.current_price)}</span>
        </div>

        <div>
          <span className="text-[10px] text-slate-500 block uppercase font-mono">Target (TP1)</span>
          <span className="text-sm font-bold text-emerald-400 font-mono">{formatUsd(trade.tp1_price)}</span>
        </div>

        <div>
          <span className="text-[10px] text-slate-500 block uppercase font-mono">
            {isClosed ? "Realized Return" : "Floating PnL"}
          </span>
          <span
            className={`text-sm font-black font-mono flex items-center gap-0.5 ${
              currentReturnPct >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {currentReturnPct >= 0 ? "+" : ""}
            {currentReturnPct.toFixed(2)}%
          </span>
        </div>
      </div>

      {/* Visual Live Proximity Slider (Between SL and TP1) */}
      {!isClosed && (
        <div className="mt-3.5 space-y-1.5">
          <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
            <span className="text-rose-400 flex items-center gap-1">
              <ShieldAlert className="h-3 w-3" /> Stop: {formatUsd(trade.sl_price)}
            </span>
            <span className="text-slate-500">Live Progress: {progressPct.toFixed(0)}%</span>
            <span className="text-emerald-400 flex items-center gap-1">
              <Target className="h-3 w-3" /> TP1: {formatUsd(trade.tp1_price)}
            </span>
          </div>

          <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden relative">
            <div
              className={`h-full transition-all duration-500 rounded-full ${
                progressPct >= 50
                  ? "bg-gradient-to-r from-cyan-500 to-emerald-400"
                  : "bg-gradient-to-r from-rose-500 to-amber-400"
              }`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Footer Details: Timestamps & Action Buttons */}
      <div className="mt-3.5 flex items-center justify-between text-[11px] text-slate-500 flex-wrap gap-2 pt-2 border-t border-slate-800/40 font-mono">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3 text-slate-400" /> Opened: {trade.taken_at_utc}
          </span>
          {trade.expires_at_utc && (
            <span className="hidden sm:inline">Expiry: {trade.expires_at_utc}</span>
          )}
        </div>

        {!isClosed && (
          <button
            onClick={() => onCloseTrade(trade.id)}
            className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold transition-all flex items-center gap-1"
          >
            Close Position Now
          </button>
        )}
      </div>
    </div>
  );
}
