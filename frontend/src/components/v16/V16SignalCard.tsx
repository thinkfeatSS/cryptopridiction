"use client";

import React, { useMemo } from "react";
import { V16SignalEnvelope } from "@/types/v16";
import { formatPrice, formatPercent, formatProbability, getGradeBadge, getRegimeTheme } from "@/lib/utils/v16";
import {
  TrendingUp,
  TrendingDown,
  Shield,
  Target,
  Sparkles,
  Zap,
  Layers,
  Clock,
  Lock,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Activity,
  BarChart2,
  ExternalLink
} from "lucide-react";

interface V16SignalCardProps {
  signal: V16SignalEnvelope;
  onSelect: (signal: V16SignalEnvelope) => void;
  isSelected?: boolean;
}

export default function V16SignalCard({ signal, onSelect, isSelected = false }: V16SignalCardProps) {
  const imm = signal.immutable;
  const dyn = signal.dynamic;

  const isLong = (imm.direction || "").toUpperCase() === "LONG";
  const gradeBadge = getGradeBadge(imm.grade);
  const regimeTheme = getRegimeTheme(imm.regime);

  // Status determination strictly aligned with app/quant_v16/audit.py
  const statusCategory = useMemo(() => {
    const st = (dyn?.status || imm?.status || "").trim().toUpperCase();
    const out = (dyn?.outcome_label || "").trim().toUpperCase();

    // 1. Pending / Active trades (Strict Gate: must be evaluated first per Rule 9)
    const pendingStatuses = [
      "PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "RESTING_LIMIT",
      "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
    ];
    if (
      pendingStatuses.includes(st) ||
      st === "ACTIVE" ||
      out.includes("ACTIVE") ||
      out.includes("PENDING") ||
      out.includes("RUNNING") ||
      out.includes("AWAIT") ||
      out.includes("RESTING")
    ) {
      if (st.includes("RESTING") || st.includes("LIMIT") || out.includes("LIMIT")) {
        return { label: dyn?.outcome_label || "RESTING LIMIT", color: "text-cyan-300 bg-cyan-950/70 border-cyan-500/50 animate-pulse", isActive: true };
      }
      return { label: dyn?.outcome_label || "ACTIVE SIGNAL", color: "text-emerald-300 bg-emerald-950/70 border-emerald-500/40 animate-pulse", isActive: true };
    }

    // 2. Breakeven outcomes
    const beStatuses = [
      "WON_TIER0_BE", "WON_TP1_BE", "EXPIRED_BREAKEVEN",
      "BREAKEVEN_EXP", "TIER0_BE_HIT", "BREAKEVEN", "BREAKEVEN_GUARD",
      "STOP_LOSS_BREAKEVEN", "TIER0_GUARD"
    ];
    if (
      beStatuses.includes(st) ||
      st.includes("BREAKEVEN") ||
      st.includes("BE_") ||
      st.includes("TIER0_BE") ||
      st.includes("SOFT_BE") ||
      out.includes("BREAKEVEN") ||
      out.includes("TIER-0") ||
      out.includes("BE RUNNER") ||
      out.includes("(BE")
    ) {
      return { label: dyn?.outcome_label || "BREAKEVEN GUARD", color: "text-amber-400 bg-amber-950/70 border-amber-500/50", isBe: true };
    }

    // 3. Won outcomes
    const wonStatuses = [
      "WON_TP3", "WON_TP2_TRAIL", "WON_TP2", "WON_TP1",
      "WON_TP2_EXP", "WON_TP1_EXP", "WON_EXP_PROFIT", "WON_PROFIT_EXPIRED", "WON",
      "WON_PROFIT_RATCHET"
    ];
    if (
      wonStatuses.includes(st) ||
      st.includes("WON") ||
      (out.includes("WON") && !out.includes("LOST")) ||
      out.includes("TP HIT") ||
      out.includes("TP1 HIT") ||
      out.includes("TP2 HIT") ||
      out.includes("TP3 HIT") ||
      st.includes("PROFIT_EXPIRED") ||
      out.includes("PROFIT")
    ) {
      return { label: dyn?.outcome_label || "TP HIT (WON)", color: "text-emerald-400 bg-emerald-950/70 border-emerald-500/50", isWon: true };
    }

    // 4. Lost outcomes
    const lostStatuses = ["LOST_SL", "LOST_EXP", "LOST_EXPIRED", "LOST"];
    if (
      lostStatuses.includes(st) ||
      st.includes("LOST") ||
      (out.includes("LOST") && !out.includes("WON")) ||
      st.includes("STOP_LOSS") ||
      out.includes("SL HIT") ||
      out.includes("STOPPED")
    ) {
      return { label: dyn?.outcome_label || "STOPPED (LOST)", color: "text-rose-400 bg-rose-950/70 border-rose-500/50", isLost: true };
    }

    // 5. Expired outcomes
    if (
      st.includes("EXP") ||
      out.includes("EXPIRED") ||
      out.includes("MISSED") ||
      out.includes("TIMEOUT") ||
      st.includes("STAGNATION")
    ) {
      return { label: dyn?.outcome_label || "EXPIRED", color: "text-slate-400 bg-slate-900 border-slate-700", isExpired: true };
    }

    return { label: dyn?.outcome_label || "ACTIVE SIGNAL", color: "text-emerald-300 bg-emerald-950/70 border-emerald-500/40", isActive: true };
  }, [dyn?.status, dyn?.outcome_label, imm?.status]);

  // Current price and live PnL calculation
  const entryPrice = imm.entry_price_initial || 0;
  const currentPrice = dyn?.current_price || entryPrice;
  const pnlPct = dyn?.unrealized_net_pnl_pct !== undefined ? dyn.unrealized_net_pnl_pct : 0;
  const mfePct = dyn?.mfe_pct || 0;
  const maePct = dyn?.mae_pct || 0;

  // Distances to TP1 and SL
  const slPrice = dyn?.current_sl || imm.sl_initial || 0;
  const tp1Price = imm.tp1_initial || 0;
  const tp2Price = imm.tp2_initial || 0;
  const tp3Price = imm.tp3_initial || 0;

  const slDistPct = entryPrice > 0 ? (Math.abs(entryPrice - slPrice) / entryPrice) * 100 : 0;
  const tp1DistPct = entryPrice > 0 ? (Math.abs(tp1Price - entryPrice) / entryPrice) * 100 : 0;
  const tp2DistPct = entryPrice > 0 ? (Math.abs(tp2Price - entryPrice) / entryPrice) * 100 : 0;

  // Trailing / Breakeven lock active
  const isBeLocked = dyn?.is_breakeven_locked || dyn?.is_tp1_locked || dyn?.locked_sl !== null || (dyn?.trailing_sl !== null && dyn?.trailing_sl !== undefined);
  const effectiveSl = dyn?.trailing_sl || dyn?.locked_sl || slPrice;

  // Defensive TP1 secured confirmation: strictly true only if is_tp1_locked is verified AND price/MFE reached target
  const isTp1ActuallySecured = useMemo(() => {
    if (!dyn?.is_tp1_locked) return false;
    if (statusCategory.isActive && entryPrice > 0 && tp1Price > 0) {
      if (isLong) {
        return currentPrice >= (tp1Price * 0.999) || (mfePct >= tp1DistPct * 0.95);
      } else {
        return currentPrice <= (tp1Price * 1.001) || (mfePct >= tp1DistPct * 0.95);
      }
    }
    return Boolean(dyn?.is_tp1_locked);
  }, [dyn?.is_tp1_locked, statusCategory.isActive, entryPrice, tp1Price, isLong, currentPrice, mfePct, tp1DistPct]);

  // Progress relative to Entry, SL, and TP1 [0% at SL, 50% at Entry, 100% at TP1]
  const tradeProgress = useMemo(() => {
    if (entryPrice <= 0 || tp1Price <= 0 || slPrice <= 0) return 50;
    if (isLong) {
      if (currentPrice >= tp1Price) return 100;
      if (currentPrice <= slPrice) return 0;
      if (currentPrice >= entryPrice) {
        return 50 + ((currentPrice - entryPrice) / Math.max(1e-8, tp1Price - entryPrice)) * 50;
      } else {
        return ((currentPrice - slPrice) / Math.max(1e-8, entryPrice - slPrice)) * 50;
      }
    } else {
      if (currentPrice <= tp1Price) return 100;
      if (currentPrice >= slPrice) return 0;
      if (currentPrice <= entryPrice) {
        return 50 + ((entryPrice - currentPrice) / Math.max(1e-8, entryPrice - tp1Price)) * 50;
      } else {
        return ((slPrice - currentPrice) / Math.max(1e-8, slPrice - entryPrice)) * 50;
      }
    }
  }, [entryPrice, tp1Price, slPrice, currentPrice, isLong]);

  return (
    <div
      onClick={() => onSelect(signal)}
      className={`group relative overflow-hidden rounded-2xl border transition-all duration-300 cursor-pointer flex flex-col justify-between ${
        isSelected
          ? "border-cyan-400 bg-slate-900/90 shadow-[0_0_30px_rgba(6,182,212,0.35)] ring-1 ring-cyan-400/50"
          : "border-slate-800/80 bg-slate-900/60 hover:bg-slate-900/90 hover:border-slate-700/90 hover:shadow-[0_8px_30px_rgba(0,0,0,0.5)]"
      }`}
    >
      {/* Soft Ambient Radial for Direction */}
      <div
        className={`absolute -top-16 -right-16 w-36 h-36 rounded-full blur-3xl pointer-events-none transition-opacity duration-300 ${
          isLong ? "bg-emerald-500/10 group-hover:bg-emerald-500/20" : "bg-rose-500/10 group-hover:bg-rose-500/20"
        }`}
      />

      {/* ========================================================= */}
      {/* 1. CARD HEADER */}
      {/* ========================================================= */}
      <div className="p-4 border-b border-slate-800/70 relative z-10">
        <div className="flex items-start justify-between gap-2">
          {/* Symbol, Direction, Horizon */}
          <div className="flex items-center gap-2.5">
            <div
              className={`w-9 h-9 rounded-xl flex items-center justify-center font-mono font-black text-xs border ${
                isLong
                  ? "bg-emerald-950/60 text-emerald-400 border-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.2)]"
                  : "bg-rose-950/60 text-rose-400 border-rose-500/40 shadow-[0_0_12px_rgba(244,63,94,0.2)]"
              }`}
            >
              {isLong ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            </div>

            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-black text-sm text-white tracking-tight group-hover:text-cyan-300 transition-colors">
                  {imm.symbol}
                </span>
                <span
                  className={`px-2 py-0.5 rounded-md text-[10px] font-mono font-bold uppercase border ${
                    isLong
                      ? "bg-emerald-950/60 text-emerald-300 border-emerald-500/30"
                      : "bg-rose-950/60 text-rose-300 border-rose-500/30"
                  }`}
                >
                  {imm.direction}
                </span>
                <span className="px-2 py-0.5 rounded-md text-[10px] font-mono font-bold bg-slate-800/90 text-cyan-300 border border-cyan-500/30">
                  {imm.horizon}
                </span>
              </div>

              <div className="flex items-center gap-2 mt-1 text-[11px] font-mono text-slate-400">
                <span>Score: <strong className="text-slate-200">{imm.signal_score || 85}</strong>/100</span>
                <span>•</span>
                <span className="truncate max-w-[120px]" title={imm.trade_thesis_id}>
                  {imm.trade_thesis_id}
                </span>
              </div>
            </div>
          </div>

          {/* Quality Grade & Status Badge */}
          <div className="flex flex-col items-end gap-1.5">
            <span className={`px-2 py-0.5 rounded-md text-[10px] font-mono font-black uppercase border ${gradeBadge.bg} ${gradeBadge.border} ${gradeBadge.text}`}>
              {imm.grade}
            </span>
            <span className={`px-2 py-0.5 rounded-md text-[9px] font-mono font-bold uppercase border ${statusCategory.color}`}>
              {statusCategory.label}
            </span>
          </div>
        </div>
      </div>

      {/* ========================================================= */}
      {/* 2. CORE V16 QUANTITATIVE METRICS GRID */}
      {/* ========================================================= */}
      <div className="p-4 space-y-3.5 relative z-10">
        {/* Highlighted Net EV Banner */}
        <div className="grid grid-cols-3 gap-2 p-2.5 rounded-xl bg-slate-950/70 border border-slate-800/80 font-mono text-center">
          {/* Expected Net EV */}
          <div className="flex flex-col">
            <span className="text-[9px] text-slate-400 uppercase tracking-wider font-semibold">Net Edge (EVnet)</span>
            <span className={`text-xs sm:text-sm font-black mt-0.5 ${imm.expected_net_return > 0 ? "text-cyan-300" : "text-rose-400"}`}>
              {formatPercent(imm.expected_net_return)}
            </span>
          </div>

          {/* Win Probability */}
          <div className="flex flex-col border-x border-slate-800/80 px-1">
            <span className="text-[9px] text-slate-400 uppercase tracking-wider font-semibold">Win Prob P(TP1)</span>
            <span className="text-xs sm:text-sm font-black text-emerald-400 mt-0.5">
              {formatProbability(imm.p_tp1)}
            </span>
          </div>

          {/* Risk to Reward */}
          <div className="flex flex-col">
            <span className="text-[9px] text-slate-400 uppercase tracking-wider font-semibold">Risk:Reward</span>
            <span className="text-xs sm:text-sm font-black text-amber-300 mt-0.5">
              1:{imm.risk_reward ? imm.risk_reward.toFixed(2) : "2.00"}
            </span>
          </div>
        </div>

        {/* Level Architecture Ladder: Entry, SL, TP1, TP2 */}
        <div className="space-y-1.5 text-xs font-mono">
          {/* Entry & Live Price */}
          <div className="flex items-center justify-between p-2 rounded-lg bg-slate-950/40 border border-slate-800/50">
            <span className="text-[11px] text-slate-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
              <span>Entry Anchor:</span>
            </span>
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-200">{formatPrice(entryPrice)}</span>
              {currentPrice !== entryPrice && (
                <span className={`text-[10px] px-1.5 py-0.2 rounded font-bold ${pnlPct >= 0 ? "bg-emerald-950 text-emerald-400" : "bg-rose-950 text-rose-400"}`}>
                  Live: {formatPrice(currentPrice)} ({formatPercent(pnlPct)})
                </span>
              )}
            </div>
          </div>

          {/* Stop Loss (with breakeven/trailing status) */}
          <div className="flex items-center justify-between p-2 rounded-lg bg-slate-950/40 border border-slate-800/50">
            <span className="text-[11px] text-slate-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
              <span>Stop Loss (SL):</span>
            </span>
            <div className="flex items-center gap-1.5">
              {(isBeLocked || (entryPrice > 0 && effectiveSl > 0 && (isLong ? effectiveSl >= entryPrice : effectiveSl <= entryPrice))) && (
                <span className="text-[9px] px-1 py-0.2 rounded bg-amber-950/80 border border-amber-500/40 text-amber-300 font-bold flex items-center gap-1">
                  <Lock className="w-2.5 h-2.5" /> BE LOCK
                </span>
              )}
              {(() => {
                const isSlInProfit = entryPrice > 0 && effectiveSl > 0 && (isLong ? effectiveSl >= entryPrice : effectiveSl <= entryPrice);
                return (
                  <>
                    <span className={`font-bold ${isSlInProfit ? "text-emerald-400" : "text-rose-400"}`}>{formatPrice(effectiveSl)}</span>
                    <span className={`text-[10px] ${isSlInProfit ? "text-emerald-400/80" : "text-rose-400/80"}`}>
                      ({isSlInProfit ? "+" : "-"}{slDistPct.toFixed(1)}%)
                    </span>
                  </>
                );
              })()}
            </div>
          </div>

          {/* Take Profit 1 */}
          <div className="flex items-center justify-between p-2 rounded-lg bg-slate-950/40 border border-slate-800/50">
            <span className="text-[11px] text-slate-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span>Take Profit 1 (TP1):</span>
            </span>
            <div className="flex items-center gap-1.5">
              {isTp1ActuallySecured && (
                <span className="text-[9px] px-1 py-0.2 rounded bg-emerald-950/80 border border-emerald-500/40 text-emerald-300 font-bold flex items-center gap-1">
                  <CheckCircle2 className="w-2.5 h-2.5 text-emerald-400" /> SECURED
                </span>
              )}
              <span className="font-bold text-emerald-400">{formatPrice(tp1Price)}</span>
              <span className="text-[10px] text-emerald-400/80">(+{tp1DistPct.toFixed(1)}%)</span>
            </div>
          </div>

          {/* Take Profit 2 (if present) */}
          {tp2Price > 0 && (
            <div className="flex items-center justify-between px-2 py-1 text-[11px] text-slate-400">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/60" />
                <span>Take Profit 2 (TP2):</span>
              </span>
              <div className="flex items-center gap-1.5">
                <span className="font-bold text-emerald-300/90">{formatPrice(tp2Price)}</span>
                <span className="text-[10px] text-emerald-300/70">(+{tp2DistPct.toFixed(1)}%)</span>
              </div>
            </div>
          )}
        </div>

        {/* Trade Progress & Excursion Bar */}
        <div className="space-y-1 pt-1 font-mono">
          <div className="flex justify-between items-center text-[10px] text-slate-400">
            <span>SL: {formatPrice(slPrice)}</span>
            <span className="font-bold text-slate-300">
              MFE: <span className="text-emerald-400">+{mfePct.toFixed(2)}%</span> • MAE: <span className="text-rose-400">-{maePct.toFixed(2)}%</span>
            </span>
            <span>TP1: {formatPrice(tp1Price)}</span>
          </div>
          <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden relative">
            <div
              className={`h-full transition-all duration-500 rounded-full ${
                tradeProgress >= 50
                  ? "bg-gradient-to-r from-cyan-500 to-emerald-400"
                  : "bg-gradient-to-r from-rose-500 to-amber-400"
              }`}
              style={{ width: `${Math.min(100, Math.max(2, tradeProgress))}%` }}
            />
          </div>
        </div>
      </div>

      {/* ========================================================= */}
      {/* 3. CARD FOOTER */}
      {/* ========================================================= */}
      <div className="p-3 bg-slate-950/70 border-t border-slate-800/80 flex items-center justify-between text-[11px] font-mono relative z-10">
        {/* Regime Pill */}
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${regimeTheme.dot}`} />
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${regimeTheme.bg} ${regimeTheme.text} border ${regimeTheme.border}`}>
            {regimeTheme.label}
          </span>
        </div>

        {/* Action button */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onSelect(signal);
          }}
          className="flex items-center gap-1 text-[11px] font-bold text-cyan-400 hover:text-cyan-300 transition-colors py-0.5 px-2 rounded-md hover:bg-cyan-950/50"
        >
          <span>Deep Audit</span>
          <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>
    </div>
  );
}
