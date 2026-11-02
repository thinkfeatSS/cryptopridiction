"use client";

import React, { useState, useMemo, useEffect } from "react";
import { useTrackedTrades } from "@/hooks/useTrackedTrades";
import { useForecastQuery } from "@/hooks/useCryptoData";
import UserTradeCard from "@/components/UserTradeCard";
import Link from "next/link";
import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  TrendingUp,
  Trash2,
  ExternalLink,
  Target,
  Sparkles,
  Zap,
} from "lucide-react";

export default function MyTradesPage() {
  const {
    activeTrades,
    closedTrades,
    closeTrade,
    removeTrade,
    clearResolvedTrades,
    syncWithLivePrices,
    isLoaded,
  } = useTrackedTrades();

  const { data: forecast } = useForecastQuery();
  const [activeTab, setActiveTab] = useState<"ACTIVE" | "HISTORY">("ACTIVE");

  // Build live price map from forecast data and sync with open trades
  useEffect(() => {
    if (!forecast) return;
    const priceMap: Record<string, number> = {};

    const allSignals = [
      ...(forecast.dominant_signals_per_coin || []),
      ...(forecast.top_round_signals || []),
    ];

    for (const sig of allSignals) {
      if (!sig.symbol) continue;
      const clean = sig.symbol.toUpperCase().replace("/", "").replace(":USDT", "");
      const p = Number(sig.current_price || sig.entry_price || 0);
      if (p > 0) {
        priceMap[clean] = p;
        priceMap[sig.symbol] = p;
      }
    }

    syncWithLivePrices(priceMap);
  }, [forecast, syncWithLivePrices]);

  // Aggregate user performance stats
  const performanceStats = useMemo(() => {
    const totalTaken = activeTrades.length + closedTrades.length;
    const wins = closedTrades.filter((t) => t.status.startsWith("WON")).length;
    const losses = closedTrades.filter((t) => t.status.startsWith("LOST")).length;
    const bes = closedTrades.filter((t) => t.status === "BREAKEVEN").length;

    const decisive = wins + losses;
    const winRate = decisive > 0 ? (wins / decisive) * 100 : 0;

    const totalReturn = closedTrades.reduce((acc, t) => acc + (t.realized_pnl_pct || 0), 0);

    return { totalTaken, wins, losses, bes, winRate, totalReturn };
  }, [activeTrades, closedTrades]);

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between border-b border-slate-800/80 pb-4 gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-400">
              <Activity className="h-4 w-4" />
            </span>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-white">
              My Personal Trading Desk
            </h1>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Real-time tracking of signals you have taken: live floating PnL, automated TP/SL break-even protection, and history.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-dark-900 hover:bg-slate-800 text-xs font-semibold text-cyan-300 border border-slate-800 hover:border-cyan-500/50 transition-all"
          >
            <Zap className="h-3.5 w-3.5" />
            <span>Browse Active Signals</span>
          </Link>
        </div>
      </div>

      {/* KPI Performance Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-dark-900/60">
          <span className="text-[11px] text-slate-500 block uppercase font-mono">In-Flight Trades</span>
          <span className="text-xl font-black text-white font-mono mt-1 block">
            {activeTrades.length} <span className="text-xs text-amber-400 font-normal">Active</span>
          </span>
        </div>

        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-dark-900/60">
          <span className="text-[11px] text-slate-500 block uppercase font-mono">Win Rate (Decisive)</span>
          <span className="text-xl font-black text-cyan-300 font-mono mt-1 block">
            {performanceStats.winRate.toFixed(1)}%
          </span>
        </div>

        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-dark-900/60">
          <span className="text-[11px] text-slate-500 block uppercase font-mono">Record (W / L / BE)</span>
          <span className="text-xl font-black text-white font-mono mt-1 flex items-center gap-1.5">
            <span className="text-emerald-400">{performanceStats.wins}W</span>
            <span className="text-slate-600">/</span>
            <span className="text-rose-400">{performanceStats.losses}L</span>
            <span className="text-slate-600">/</span>
            <span className="text-slate-400">{performanceStats.bes}BE</span>
          </span>
        </div>

        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-dark-900/60">
          <span className="text-[11px] text-slate-500 block uppercase font-mono">Realized Return</span>
          <span
            className={`text-xl font-black font-mono mt-1 block ${
              performanceStats.totalReturn >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {performanceStats.totalReturn >= 0 ? "+" : ""}
            {performanceStats.totalReturn.toFixed(2)}%
          </span>
        </div>
      </div>

      {/* Tabs: Active In-Flight vs. Resolved History */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveTab("ACTIVE")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold font-mono transition-all ${
              activeTab === "ACTIVE"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            <Activity className="h-3.5 w-3.5" />
            <span>Active Positions ({activeTrades.length})</span>
          </button>

          <button
            onClick={() => setActiveTab("HISTORY")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold font-mono transition-all ${
              activeTab === "HISTORY"
                ? "bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-sm"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            <Clock className="h-3.5 w-3.5" />
            <span>Resolved History ({closedTrades.length})</span>
          </button>
        </div>

        {activeTab === "HISTORY" && closedTrades.length > 0 && (
          <button
            onClick={clearResolvedTrades}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-rose-400 hover:text-rose-300 hover:bg-rose-950/40 transition-colors border border-rose-900/40"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>Clear History</span>
          </button>
        )}
      </div>

      {/* Main Content Area */}
      {activeTab === "ACTIVE" ? (
        activeTrades.length === 0 ? (
          <div className="glass-panel p-10 rounded-2xl border border-slate-800 text-center space-y-3">
            <div className="w-12 h-12 rounded-2xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center mx-auto text-cyan-400">
              <Target className="h-6 w-6" />
            </div>
            <h3 className="text-base font-bold text-white">No Active Positions Being Tracked</h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
              When you see a signal you like on the main terminal, click <span className="text-cyan-300 font-bold">&quot;Take Trade&quot;</span> to track its real-time progress, TP1 targets, and break-even invalidation right here.
            </p>
            <div className="pt-2">
              <Link
                href="/"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-cyan-950/40 transition-all"
              >
                <Zap className="h-4 w-4" />
                <span>Go to Live Signals Matrix</span>
              </Link>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {activeTrades.map((trade) => (
              <UserTradeCard
                key={trade.id}
                trade={trade}
                onCloseTrade={closeTrade}
                onRemoveTrade={removeTrade}
              />
            ))}
          </div>
        )
      ) : (
        closedTrades.length === 0 ? (
          <div className="glass-panel p-10 rounded-2xl border border-slate-800 text-center space-y-2">
            <Clock className="h-8 w-8 text-slate-600 mx-auto" />
            <h3 className="text-sm font-bold text-slate-400">No Resolved Trade History Yet</h3>
            <p className="text-xs text-slate-500">
              Closed or expired trades will be logged here with realized return percentages.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {closedTrades.map((trade) => (
              <UserTradeCard
                key={trade.id}
                trade={trade}
                onCloseTrade={closeTrade}
                onRemoveTrade={removeTrade}
              />
            ))}
          </div>
        )
      )}
    </div>
  );
}
