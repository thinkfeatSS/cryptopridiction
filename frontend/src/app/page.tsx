"use client";

import React, { useState } from "react";
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

  const topSignals = forecast?.top_round_signals || [];

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
              Real-time multi-horizon confluence setups evaluated on the 15-minute candle close with strict 1:2 Risk:Reward invalidations.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="rounded-lg bg-dark-900/90 px-3 py-1.5 text-slate-300 border border-slate-800 flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-cyan-400" />
              <span>Active Setups: <strong className="text-cyan-300">{topSignals.length}</strong></span>
            </span>
          </div>
        </div>

        {/* 1.1 Actionable Top Institutional Signal Cards (Grade A+ / Grade A) */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5 font-mono">
              <Sparkles className="h-4 w-4 text-cyan-400" /> Top Actionable Signals ({topSignals.length} Active This Round)
            </h2>
            <span className="text-[11px] text-slate-500 font-mono">
              Highest-Edge Confluence Filter
            </span>
          </div>

          {isLoading ? (
            <div className="py-12 text-center text-xs text-slate-500 font-mono glass-panel rounded-2xl">
              Loading actionable institutional setup cards...
            </div>
          ) : topSignals.length === 0 ? (
            <div className="glass-panel rounded-2xl p-8 text-center text-slate-400 border border-slate-800">
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-dark-900 border border-slate-800 text-slate-500 mb-2">
                <Zap className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-bold text-white">No Grade A+ Setups Firing Right Now</h3>
              <p className="text-xs text-slate-400 mt-1">
                Market is in defensive mode. Next full scan will evaluate new entries on the 15-minute candle mark.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {topSignals.map((sig: any, idx: number) => (
                <SignalCard key={sig.signal_id || idx} signal={sig} rankIndex={idx} />
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
