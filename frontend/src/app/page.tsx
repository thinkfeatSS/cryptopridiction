"use client";

import React, { useState, useMemo } from "react";
import KpiMetrics from "@/components/KpiMetrics";
import BtcSignalSection from "@/components/BtcSignalSection";
import SignalCard from "@/components/SignalCard";
import AssetPredictionMatrix from "@/components/AssetPredictionMatrix";
import DailySignalsView from "@/components/DailySignalsView";
import SignalsTable from "@/components/SignalsTable";
import PortfolioView from "@/components/PortfolioView";
import QueuedTrades from "@/components/QueuedTrades";
import { useForecastQuery } from "@/hooks/useCryptoData";
import { Sparkles, Zap, ShieldCheck, Activity, BarChart2 } from "lucide-react";

export default function DashboardPage() {
  const { data: forecast, isLoading } = useForecastQuery();
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [activeHorizon, setActiveHorizon] = useState<string>("ALL");

  const topSignals = forecast?.top_round_signals || [];
  const signalsByHorizon = forecast?.signals_by_horizon || {};

  const horizonCategories = [
    { key: "ALL", label: "⚡ All Active", tag: "ALL" },
    { key: "15M", label: "⚡ Scalp (15M)", tag: "15M" },
    { key: "1H", label: "🌊 Swing (1H)", tag: "1H" },
    { key: "4H", label: "⏳ Intraday (4H)", tag: "4H" },
    { key: "24H", label: "🚀 Macro (24H)", tag: "24H" },
    { key: "7D", label: "🗓️ Weekly (7D)", tag: "7D" },
    { key: "30D", label: "🪐 Monthly (30D)", tag: "30D" },
  ];

  // Helper to count active setups per horizon category
  const getHorizonCount = (tag: string) => {
    if (tag === "ALL") return topSignals.length;
    if (signalsByHorizon[tag]) return signalsByHorizon[tag].length;
    return topSignals.filter((s: any) => {
      const hStr = (s.horizon_tag || s.horizon || s.horizon_name || "").toUpperCase();
      if (tag === "15M") return hStr.includes("15M") || hStr.includes("SCALP");
      if (tag === "1H") return hStr.includes("1H") || hStr.includes("SWING");
      if (tag === "4H") return hStr.includes("4H") || hStr.includes("INTRADAY") || hStr.includes("4-HOUR");
      if (tag === "24H") return hStr.includes("24H") || hStr.includes("MACRO") || hStr.includes("1D");
      if (tag === "7D") return hStr.includes("7D") || hStr.includes("WEEKLY");
      if (tag === "30D") return hStr.includes("30D") || hStr.includes("MONTHLY");
      return false;
    }).length;
  };

  // Filter signals according to active horizon
  const filteredTopSignals = useMemo(() => {
    if (activeHorizon === "ALL") {
      return topSignals.filter((s: any) => {
        const exp = s.expected_return_pct ?? (s.exp_return ? s.exp_return * 100 : 0.0);
        return Math.abs(exp) >= 0.40;
      });
    }

    if (signalsByHorizon[activeHorizon] && signalsByHorizon[activeHorizon].length > 0) {
      return signalsByHorizon[activeHorizon];
    }

    return topSignals.filter((s: any) => {
      const exp = s.expected_return_pct ?? (s.exp_return ? s.exp_return * 100 : 0.0);
      if (Math.abs(exp) < 0.40) return false;

      const hStr = (s.horizon_tag || s.horizon || s.horizon_name || "").toUpperCase();
      if (activeHorizon === "15M") return hStr.includes("15M") || hStr.includes("SCALP");
      if (activeHorizon === "1H") return hStr.includes("1H") || hStr.includes("SWING");
      if (activeHorizon === "4H") return hStr.includes("4H") || hStr.includes("INTRADAY") || hStr.includes("4-HOUR");
      if (activeHorizon === "24H") return hStr.includes("24H") || hStr.includes("MACRO") || hStr.includes("1D");
      if (activeHorizon === "7D") return hStr.includes("7D") || hStr.includes("WEEKLY");
      if (activeHorizon === "30D") return hStr.includes("30D") || hStr.includes("MONTHLY");
      return false;
    });
  }, [topSignals, signalsByHorizon, activeHorizon]);

  return (
    <div className="space-y-8">
      {/* ========================================================= */}
      {/* 1. HERO SECTION: Actionable Signals & Dedicated BTC Alpha */}
      {/* ========================================================= */}
      <section className="space-y-6">
        {/* Hero Banner Header */}
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between border-b border-slate-800/80 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-400">
                <Zap className="h-3.5 w-3.5 animate-pulse" />
              </span>
              <h1 className="text-xl sm:text-2xl font-black tracking-tight text-white">
                Live Institutional AI Signal Terminal
              </h1>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Timeframe-separated confluence setups (15M, 1H, 4H, 24H, Weekly, Monthly) evaluated on the 15-minute candle close with strict &ge;0.40% fee-cleared profit hurdles.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="rounded-lg bg-dark-900/90 px-3 py-1.5 text-slate-300 border border-slate-800 flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-cyan-400" />
              <span>Active Signals: <strong className="text-cyan-300">{topSignals.length}</strong></span>
            </span>
          </div>
        </div>

        {/* 1.1 Actionable Top Institutional Signal Cards by Horizon */}
        <div>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 mb-3">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5 font-mono">
              <Sparkles className="h-4 w-4 text-cyan-400" /> Timeframe-Separated Actionable Signals ({filteredTopSignals.length} Active)
            </h2>
            <span className="text-[11px] text-emerald-400 font-mono font-semibold flex items-center gap-1">
              ✓ Min 0.40% Return Filter Active (Fees Protected)
            </span>
          </div>

          {/* Horizon Category Tabs */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-2 mb-4 max-w-full">
            {horizonCategories.map((cat) => {
              const count = getHorizonCount(cat.tag);
              const isActive = activeHorizon === cat.tag;
              return (
                <button
                  key={cat.key}
                  type="button"
                  onClick={() => setActiveHorizon(cat.tag)}
                  className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl px-3 py-1.5 text-xs font-bold transition-all ${
                    isActive
                      ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20"
                      : "bg-dark-900/90 text-slate-400 hover:text-slate-200 border border-slate-800"
                  }`}
                >
                  <span>{cat.label}</span>
                  <span
                    className={`rounded-full px-1.5 py-0.2 text-[10px] font-mono ${
                      count > 0
                        ? isActive
                          ? "bg-cyan-400 text-dark-950 font-black"
                          : "bg-cyan-950 text-cyan-400 border border-cyan-700/50"
                        : "bg-slate-800 text-slate-500"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {isLoading ? (
            <div className="py-12 text-center text-xs text-slate-500 font-mono glass-panel rounded-2xl">
              Loading actionable institutional setup cards across horizons...
            </div>
          ) : filteredTopSignals.length === 0 ? (
            <div className="glass-panel rounded-2xl p-8 text-center text-slate-400 border border-slate-800">
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-dark-900 border border-slate-800 text-slate-500 mb-2">
                <Zap className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-bold text-white">
                {activeHorizon === "ALL"
                  ? "No Grade A+ Setups Firing Right Now"
                  : `No High-Potential Setups in ${activeHorizon} This Round`}
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                {activeHorizon === "ALL"
                  ? "Market is in defensive mode. Next full scan will evaluate new entries on the 15-minute candle mark."
                  : `This timeframe was skipped for safety because no asset met the strict ≥0.40% net gain and confluence criteria. Next evaluation in 15 minutes.`}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filteredTopSignals.map((sig: any, idx: number) => (
                <SignalCard key={sig.signal_id || `${sig.symbol}-${idx}`} signal={sig} rankIndex={idx} />
              ))}
            </div>
          )}
        </div>

        {/* 1.2 Dedicated Bitcoin (BTC) Intelligence & Command Station */}
        <BtcSignalSection />

        {/* 1.3 Executive Performance KPI Summary Ribbon */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5 font-mono">
              <ShieldCheck className="h-4 w-4 text-cyan-400" /> Executive Performance KPI Overview
            </h2>
            <span className="text-[11px] text-slate-500 font-mono">
              Auto-Syncing with MySQL Database
            </span>
          </div>
          <KpiMetrics />
        </div>
      </section>

      {/* ========================================================= */}
      {/* 2. COMPLETE PREDICTION SECTION: Top 100 Asset Universe     */}
      {/* ========================================================= */}
      <section>
        <AssetPredictionMatrix />
      </section>

      {/* ========================================================= */}
      {/* 3. PAPER TRADING BOT: Virtual Positions & Balance         */}
      {/* ========================================================= */}
      <section className="space-y-6">
        <PortfolioView />
        <QueuedTrades />
      </section>

      {/* ========================================================= */}
      {/* 4. AUDIT LEDGER & DAILY BREAKDOWN: 100% Verifiable Record */}
      {/* ========================================================= */}
      <section className="space-y-6">
        <DailySignalsView
          selectedDate={selectedDate}
          onSelectDate={(d) => setSelectedDate(d)}
        />

        <SignalsTable initialDate={selectedDate} key={selectedDate} />
      </section>
    </div>
  );
}
