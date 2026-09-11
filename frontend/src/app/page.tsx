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
  const [directionFilter, setDirectionFilter] = useState<"ALL" | "LONG" | "SHORT">("ALL");

  const topSignals = forecast?.top_round_signals || [];
  const signalsByHorizon = forecast?.signals_by_horizon || {};

  const horizonCategories = [
    { key: "ALL", label: "⚡ All Active", tag: "ALL" },
    { key: "15M", label: "⚡ Scalp (15M)", tag: "15M" },
    { key: "30M", label: "⏱️ 30M", tag: "30M" },
    { key: "1H", label: "🌊 Swing (1H)", tag: "1H" },
    { key: "4H", label: "⏳ Intraday (4H)", tag: "4H" },
    { key: "12H", label: "🌗 12H", tag: "12H" },
    { key: "24H", label: "🚀 Macro (24H)", tag: "24H" },
    { key: "4D", label: "📅 4D", tag: "4D" },
    { key: "7D", label: "🗓️ Weekly (7D)", tag: "7D" },
    { key: "15D", label: "📆 15D", tag: "15D" },
    { key: "30D", label: "🪐 Monthly (30D)", tag: "30D" },
  ];

  // Helper to count active setups per horizon category
  const getHorizonCount = (tag: string) => {
    let list = topSignals;
    if (directionFilter === "LONG") {
      list = list.filter((s: any) => s.direction === "LONG" || s.direction === "BULLISH");
    } else if (directionFilter === "SHORT") {
      list = list.filter((s: any) => s.direction === "SHORT" || s.direction === "BEARISH");
    }

    if (tag === "ALL") return list.length;
    if (signalsByHorizon[tag] && directionFilter === "ALL") return signalsByHorizon[tag].length;
    return list.filter((s: any) => {
      const hStr = (s.horizon_tag || s.horizon || s.horizon_name || s.horizon_key || "").toUpperCase();
      if (tag === "15M") return hStr.includes("15M") || hStr.includes("SCALP");
      if (tag === "30M") return hStr.includes("30M");
      if (tag === "1H") return hStr.includes("1H") || hStr.includes("SWING");
      if (tag === "4H") return hStr.includes("4H") || hStr.includes("INTRADAY") || hStr.includes("4-HOUR");
      if (tag === "12H") return hStr.includes("12H");
      if (tag === "24H") return hStr.includes("24H") || hStr.includes("MACRO") || hStr.includes("1D");
      if (tag === "4D") return hStr.includes("4D");
      if (tag === "7D") return hStr.includes("7D") || hStr.includes("WEEKLY");
      if (tag === "15D") return hStr.includes("15D") || hStr.includes("BIWEEKLY");
      if (tag === "30D") return hStr.includes("30D") || hStr.includes("MONTHLY");
      return false;
    }).length;
  };

  const longCount = useMemo(() => {
    return topSignals.filter((s: any) => s.direction === "LONG" || s.direction === "BULLISH").length;
  }, [topSignals]);

  const shortCount = useMemo(() => {
    return topSignals.filter((s: any) => s.direction === "SHORT" || s.direction === "BEARISH").length;
  }, [topSignals]);

  // Filter signals according to active horizon & direction filter
  const filteredTopSignals = useMemo(() => {
    let list: any[] = [];
    if (activeHorizon === "ALL") {
      list = topSignals.filter((s: any) => {
        const exp = s.expected_return_pct ?? (s.exp_return ? s.exp_return * 100 : 0.0);
        return Math.abs(exp) >= 0.40;
      });
    } else if (signalsByHorizon[activeHorizon] && signalsByHorizon[activeHorizon].length > 0 && directionFilter === "ALL") {
      list = signalsByHorizon[activeHorizon];
    } else {
      list = topSignals.filter((s: any) => {
        const exp = s.expected_return_pct ?? (s.exp_return ? s.exp_return * 100 : 0.0);
        if (Math.abs(exp) < 0.40) return false;

        const hStr = (s.horizon_tag || s.horizon || s.horizon_name || s.horizon_key || "").toUpperCase();
        if (activeHorizon === "15M") return hStr.includes("15M") || hStr.includes("SCALP");
        if (activeHorizon === "30M") return hStr.includes("30M");
        if (activeHorizon === "1H") return hStr.includes("1H") || hStr.includes("SWING");
        if (activeHorizon === "4H") return hStr.includes("4H") || hStr.includes("INTRADAY") || hStr.includes("4-HOUR");
        if (activeHorizon === "12H") return hStr.includes("12H");
        if (activeHorizon === "24H") return hStr.includes("24H") || hStr.includes("MACRO") || hStr.includes("1D");
        if (activeHorizon === "4D") return hStr.includes("4D");
        if (activeHorizon === "7D") return hStr.includes("7D") || hStr.includes("WEEKLY");
        if (activeHorizon === "15D") return hStr.includes("15D") || hStr.includes("BIWEEKLY");
        if (activeHorizon === "30D") return hStr.includes("30D") || hStr.includes("MONTHLY");
        return false;
      });
    }

    if (directionFilter === "LONG") {
      list = list.filter((s: any) => s.direction === "LONG" || s.direction === "BULLISH");
    } else if (directionFilter === "SHORT") {
      list = list.filter((s: any) => s.direction === "SHORT" || s.direction === "BEARISH");
    }

    return list;
  }, [topSignals, signalsByHorizon, activeHorizon, directionFilter]);

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
              Timeframe-separated confluence setups (15M, 30M, 1H, 4H, 12H, 24H, 4D, 7D, 15D, 30D) actively maintained until Win, Loss, or Expire with strict &ge;0.40% profit hurdles.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="rounded-lg bg-dark-900/90 px-3 py-1.5 text-slate-300 border border-slate-800 flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-cyan-400" />
              <span>Active Signals: <strong className="text-cyan-300">{topSignals.length}</strong></span>
            </span>
          </div>
        </div>

        {/* 1.1 Actionable Top Institutional Signal Cards by Horizon & Direction */}
        <div>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 mb-3">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5 font-mono">
              <Sparkles className="h-4 w-4 text-cyan-400" /> Timeframe-Separated Actionable Signals ({filteredTopSignals.length} Active)
            </h2>
            <span className="text-[11px] text-emerald-400 font-mono font-semibold flex items-center gap-1">
              ✓ Min 0.40% Return Filter Active (Fees Protected)
            </span>
          </div>

          {/* Controls Bar: Direction Filters + Horizon Category Tabs */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4 bg-dark-900/80 p-2.5 rounded-2xl border border-slate-800/90">
            {/* Direction Filter Buttons */}
            <div className="flex items-center gap-1.5 bg-dark-950/90 p-1 rounded-xl border border-slate-800 shrink-0">
              <span className="text-[10px] uppercase font-bold text-slate-500 px-2 font-mono">Side:</span>
              <button
                type="button"
                onClick={() => setDirectionFilter("ALL")}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                  directionFilter === "ALL"
                    ? "bg-cyan-500/25 text-cyan-200 border border-cyan-500/40 shadow-sm"
                    : "text-slate-400 hover:text-white hover:bg-slate-800/50"
                }`}
              >
                ⚡ All ({topSignals.length})
              </button>
              <button
                type="button"
                onClick={() => setDirectionFilter("LONG")}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
                  directionFilter === "LONG"
                    ? "bg-emerald-500/25 text-emerald-300 border border-emerald-500/50 shadow-sm shadow-emerald-500/20"
                    : "text-slate-400 hover:text-emerald-300 hover:bg-slate-800/50"
                }`}
              >
                <span>🟢 Longs</span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-700/50">
                  {longCount}
                </span>
              </button>
              <button
                type="button"
                onClick={() => setDirectionFilter("SHORT")}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
                  directionFilter === "SHORT"
                    ? "bg-rose-500/25 text-rose-300 border border-rose-500/50 shadow-sm shadow-rose-500/20"
                    : "text-slate-400 hover:text-rose-300 hover:bg-slate-800/50"
                }`}
              >
                <span>🔴 Shorts</span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-rose-950 text-rose-300 border border-rose-700/50">
                  {shortCount}
                </span>
              </button>
            </div>

            {/* Horizon Category Tabs */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 max-w-full">
              {horizonCategories.map((cat) => {
                const count = getHorizonCount(cat.tag);
                const isActive = activeHorizon === cat.tag;
                return (
                  <button
                    key={cat.key}
                    type="button"
                    onClick={() => setActiveHorizon(cat.tag)}
                    className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl px-2.5 py-1.5 text-xs font-bold transition-all ${
                      isActive
                        ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20"
                        : "bg-dark-950 text-slate-400 hover:text-slate-200 border border-slate-800/80"
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
