"use client";

import React from "react";
import { formatPercent, formatUsd } from "@/lib/utils";
import {
  ArrowUpRight,
  ArrowDownRight,
  ShieldAlert,
  Target,
  Sparkles,
  Zap,
  Layers,
  Clock,
} from "lucide-react";

interface SignalCardProps {
  signal: any;
  rankIndex?: number;
}

export default function SignalCard({ signal, rankIndex = 0 }: SignalCardProps) {
  const isLong = signal.direction === "LONG" || signal.direction === "BULLISH";
  const gradeStr = signal.quality_grade || signal.grade || "Grade A";
  const isGradeAPlus = gradeStr.includes("A+");
  const conviction = signal.conviction_pct ?? signal.conviction ?? 50.0;
  const horizon = signal.horizon || signal.horizon_name || "SCALP (15M)";
  const expReturn = signal.expected_return_pct ?? (signal.exp_return ? signal.exp_return * 100 : 0.0);

  const entryPrice = signal.entry_price ?? signal.current_price ?? 0.0;
  const tp1 = signal.tp1_price ?? signal.tp_price ?? entryPrice;
  const tp2 = signal.tp2_price ?? signal.tp_price ?? entryPrice;
  const tp3 = signal.tp3_price ?? signal.tp_price ?? entryPrice;
  const sl = signal.sl_price ?? entryPrice;

  const medals = ["🥇 TOP PICK (#1)", "🥈 RUNNER UP (#2)", "🥉 BRONZE (#3)", "🎯 PICK (#4)", "🎯 PICK (#5)"];
  const rankLabel = signal.rank || (rankIndex < medals.length ? medals[rankIndex] : `#${rankIndex + 1}`);

  return (
    <div
      className={`glass-panel glass-panel-hover rounded-2xl p-5 border relative overflow-hidden transition-all duration-300 ${
        isGradeAPlus
          ? "border-cyan-500/40 shadow-lg shadow-cyan-500/10 hover:border-cyan-400"
          : "border-slate-800 hover:border-slate-700"
      }`}
    >
      {/* Background Ambient Glow */}
      <div
        className={`absolute -top-12 -right-12 h-32 w-32 rounded-full blur-3xl pointer-events-none ${
          isLong ? "bg-emerald-500/15" : "bg-rose-500/15"
        }`}
      />

      {/* Header: Rank Badge & Quality Grade */}
      <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <span className="rounded-lg bg-dark-900 px-2.5 py-1 text-xs font-bold text-slate-200 border border-slate-700/80">
            {rankLabel}
          </span>
          <span
            className={`rounded-lg px-2.5 py-1 text-xs font-bold flex items-center gap-1.5 ${
              isGradeAPlus
                ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20"
                : "bg-emerald-950/80 text-emerald-300 border border-emerald-500/40"
            }`}
          >
            <Sparkles className="h-3 w-3" />
            {isGradeAPlus ? "💎 Grade A+ (ELITE)" : "🟢 Grade A (HIGH)"}
          </span>
        </div>

        {/* Direction Badge */}
        <span
          className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-black tracking-wide ${
            isLong
              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
              : "bg-rose-500/20 text-rose-400 border border-rose-500/40"
          }`}
        >
          {isLong ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
          {isLong ? "LONG BUY" : "SHORT SELL"}
        </span>
      </div>

      {/* Asset & Horizon Bar */}
      <div className="mt-3.5 flex items-center justify-between">
        <div>
          <h3 className="text-xl font-black tracking-tight text-white flex items-center gap-1.5">
            {signal.symbol}
          </h3>
          <span className="text-xs text-slate-400 flex items-center gap-1 mt-0.5">
            <Clock className="h-3 w-3 text-cyan-400" /> {horizon}
          </span>
        </div>

        {/* Conviction & Expected Return */}
        <div className="text-right">
          <div className="flex items-baseline justify-end gap-1">
            <span className="text-xs text-slate-400 font-medium">Conviction:</span>
            <span className="text-base font-black text-cyan-400 font-mono">
              {conviction.toFixed(1)}%
            </span>
          </div>
          <span
            className={`text-xs font-bold ${
              expReturn >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            Exp: {formatPercent(expReturn)}
          </span>
        </div>
      </div>

      {/* Price Target Matrix Grid (1:2 R:R) */}
      <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-dark-900/90 p-3 border border-slate-800/80">
        <div className="flex flex-col">
          <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">
            Entry Price
          </span>
          <span className="text-sm font-black text-white font-mono mt-0.5">
            {formatUsd(entryPrice)}
          </span>
        </div>

        <div className="flex flex-col">
          <span className="text-[10px] uppercase font-bold text-rose-400 tracking-wider">
            Invalidation Stop-Loss
          </span>
          <span className="text-sm font-black text-rose-400 font-mono mt-0.5">
            {formatUsd(sl)}
          </span>
        </div>

        <div className="flex flex-col border-t border-slate-800/60 pt-2 col-span-2">
          <span className="text-[10px] uppercase font-bold text-emerald-400 tracking-wider flex items-center gap-1">
            <Target className="h-3 w-3" /> Targets (TP1 / TP2 / TP3)
          </span>
          <div className="mt-1 flex items-center justify-between text-xs font-mono text-slate-200">
            <span>
              TP1: <strong className="text-emerald-400">{formatUsd(tp1)}</strong>
            </span>
            <span>
              TP2: <strong className="text-emerald-300">{formatUsd(tp2)}</strong>
            </span>
            <span>
              TP3: <strong className="text-emerald-200">{formatUsd(tp3)}</strong>
            </span>
          </div>
        </div>
      </div>

      {/* Invalidation & Execution Decision */}
      <div className="mt-3.5 flex items-start gap-2 rounded-lg bg-dark-950/80 p-2.5 border border-slate-800/60 text-xs">
        <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="flex flex-col">
          <span className="font-semibold text-slate-200">
            {signal.decision || "🎯 INSTITUTIONAL EXECUTION SIGNAL"}
          </span>
          <span className="text-[11px] text-slate-400 mt-0.5">
            Risk: Strict 1–2% per trade. Move SL to Breakeven after TP1 touch.
          </span>
        </div>
      </div>
    </div>
  );
}
