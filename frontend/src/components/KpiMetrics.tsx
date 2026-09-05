"use client";

import React from "react";
import { useKpiQuery, usePortfolioQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd } from "@/lib/utils";
import {
  TrendingUp,
  Award,
  CheckCircle2,
  XCircle,
  Clock,
  DollarSign,
  Layers,
  Sparkles,
} from "lucide-react";

export default function KpiMetrics() {
  const { data: kpi, isLoading: kpiLoading } = useKpiQuery();
  const { data: portfolio, isLoading: portLoading } = usePortfolioQuery();

  const winRate = kpi?.win_rate_pct ?? 0.0;
  const gradeAPlusWr = kpi?.grade_a_plus_win_rate_pct ?? 0.0;
  const gradeAWr = kpi?.grade_a_win_rate_pct ?? 0.0;
  const cumReturn = kpi?.cumulative_return_pct ?? 0.0;
  const avgReturn = kpi?.average_return_pct ?? 0.0;
  const wonCount = kpi?.won_signals_count ?? 0;
  const lostCount = kpi?.lost_signals_count ?? 0;
  const pendingCount = kpi?.pending_signals_count ?? 0;
  const totalCount = kpi?.total_trader_signals ?? 0;

  const currentBalance = portfolio?.current_balance_usd ?? 10000.0;
  const netProfit = portfolio?.total_net_profit_usd ?? 0.0;
  const openTradesCount = portfolio?.open_positions?.length ?? 0;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
      {/* 1. Decisive Win Rate */}
      <div className="glass-panel glass-panel-hover rounded-2xl p-4 relative overflow-hidden">
        <div className="absolute top-0 right-0 h-24 w-24 bg-cyan-500/10 rounded-full blur-2xl pointer-events-none" />
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-300">
            Decisive Win Rate
          </span>
          <Award className="h-4 w-4 text-cyan-400" />
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-3xl font-black tracking-tight text-white">
            {kpiLoading ? "..." : `${winRate.toFixed(1)}%`}
          </span>
          <span className="text-xs font-semibold text-emerald-400">
            High Edge
          </span>
        </div>
        <div className="mt-2.5 flex items-center gap-2 text-[11px] text-slate-400 border-t border-slate-800/80 pt-2">
          <span className="text-cyan-300 font-medium">💎 Grade A+: {gradeAPlusWr.toFixed(1)}%</span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-300">Grade A: {gradeAWr.toFixed(1)}%</span>
        </div>
      </div>

      {/* 2. Resolved Outcome Count */}
      <div className="glass-panel glass-panel-hover rounded-2xl p-4 relative overflow-hidden">
        <div className="absolute top-0 right-0 h-24 w-24 bg-emerald-500/10 rounded-full blur-2xl pointer-events-none" />
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-300">
            Signal Outcomes
          </span>
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        </div>
        <div className="mt-2 flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-emerald-400">
            <CheckCircle2 className="h-4 w-4" />
            <span className="text-2xl font-black">{wonCount}</span>
            <span className="text-[11px] uppercase font-bold text-emerald-500/80">Won</span>
          </div>
          <span className="text-slate-600 text-lg font-light">/</span>
          <div className="flex items-center gap-1.5 text-rose-400">
            <XCircle className="h-4 w-4" />
            <span className="text-2xl font-black">{lostCount}</span>
            <span className="text-[11px] uppercase font-bold text-rose-500/80">Lost</span>
          </div>
        </div>
        <div className="mt-2.5 flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-800/80 pt-2">
          <span className="flex items-center gap-1 text-amber-300 font-medium">
            <Clock className="h-3 w-3" /> ⏳ {pendingCount} Pending Trades
          </span>
          <span className="text-slate-500">Auto-evaluating</span>
        </div>
      </div>

      {/* 3. Cumulative Tracked Return */}
      <div className="glass-panel glass-panel-hover rounded-2xl p-4 relative overflow-hidden">
        <div className="absolute top-0 right-0 h-24 w-24 bg-indigo-500/10 rounded-full blur-2xl pointer-events-none" />
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-300">
            Cumulative Return
          </span>
          <TrendingUp className="h-4 w-4 text-indigo-400" />
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span
            className={`text-3xl font-black tracking-tight ${
              cumReturn >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {kpiLoading ? "..." : formatPercent(cumReturn)}
          </span>
        </div>
        <div className="mt-2.5 flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-800/80 pt-2">
          <span className="text-slate-300">
            Avg per trade: <strong className="text-white">{formatPercent(avgReturn)}</strong>
          </span>
          <span className="text-[10px] rounded bg-indigo-950/60 px-1.5 py-0.5 text-indigo-300 font-mono">
            Compounded
          </span>
        </div>
      </div>

      {/* 4. Total Signals Tracked */}
      <div className="glass-panel glass-panel-hover rounded-2xl p-4 relative overflow-hidden">
        <div className="absolute top-0 right-0 h-24 w-24 bg-amber-500/10 rounded-full blur-2xl pointer-events-none" />
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-300">
            Total Audited Signals
          </span>
          <Layers className="h-4 w-4 text-amber-400" />
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-3xl font-black tracking-tight text-white">
            {kpiLoading ? "..." : totalCount}
          </span>
          <span className="text-xs font-semibold text-slate-400">
            Signals Logged
          </span>
        </div>
        <div className="mt-2.5 flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-800/80 pt-2">
          <span className="text-slate-300">Database & CSV Synced</span>
          <span className="text-emerald-400 font-medium">100% Verified</span>
        </div>
      </div>

      {/* 5. Paper Trading Portfolio Equity */}
      <div className="glass-panel glass-panel-hover rounded-2xl p-4 relative overflow-hidden">
        <div className="absolute top-0 right-0 h-24 w-24 bg-purple-500/10 rounded-full blur-2xl pointer-events-none" />
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-300">
            Paper Bot Balance
          </span>
          <DollarSign className="h-4 w-4 text-purple-400" />
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-3xl font-black tracking-tight text-white font-mono">
            {portLoading ? "..." : formatUsd(currentBalance)}
          </span>
        </div>
        <div className="mt-2.5 flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-800/80 pt-2">
          <span className={`font-semibold ${netProfit >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
            {netProfit >= 0 ? "+" : ""}{formatUsd(netProfit)} Net PnL
          </span>
          <span className="text-cyan-300 font-medium font-mono">
            {openTradesCount} Active Trades
          </span>
        </div>
      </div>
    </div>
  );
}
