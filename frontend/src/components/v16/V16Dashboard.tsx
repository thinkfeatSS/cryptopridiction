"use client";

import React, { useState, useMemo } from "react";
import V16Header from "@/components/v16/V16Header";
import V16KpiRow from "@/components/v16/V16KpiRow";
import V16RegimeCard from "@/components/v16/V16RegimeCard";
import V16ThesisPanel from "@/components/v16/V16ThesisPanel";
import V16SignalCardsGrid from "@/components/v16/V16SignalCardsGrid";
import V16SignalTable from "@/components/v16/V16SignalTable";
import V16SignalDetailModal from "@/components/v16/V16SignalDetailModal";
import V16EventJournal from "@/components/v16/V16EventJournal";
import V16PerformancePanel from "@/components/v16/V16PerformancePanel";
import V16InstitutionalIntelligenceHUD from "@/components/v16/V16InstitutionalIntelligenceHUD";
import {
  useV16Signals,
  useV16Theses,
  useV16Events,
  useV16Regime,
  useV16MarketIntelligence,
} from "@/hooks/useV16Data";
import { V16SignalEnvelope } from "@/types/v16";
import { AlertCircle, RefreshCw, Sparkles, Activity, LayoutGrid, Table } from "lucide-react";

export default function V16Dashboard() {
  const [selectedSignal, setSelectedSignal] = useState<V16SignalEnvelope | null>(null);
  const [displayMode, setDisplayMode] = useState<"CARDS" | "TABLE">("CARDS");
  const [hudSymbol, setHudSymbol] = useState<string>("BTC/USDT");

  // Live queries to V16 APIs
  const signalsQuery = useV16Signals();
  const thesesQuery = useV16Theses();
  const eventsQuery = useV16Events(50);
  const regimeQuery = useV16Regime();
  const intelligenceQuery = useV16MarketIntelligence(hudSymbol);

  const signals = signalsQuery.data?.signals || [];
  const theses = thesesQuery.data?.theses || [];
  const events = eventsQuery.data?.events || [];
  const regimeData = regimeQuery.data?.regime;
  const intelligenceData = intelligenceQuery.data?.intelligence;

  // Active signals partition (strictly excludes terminal/evaluated signals)
  const activeSignals = useMemo(() => {
    return signals.filter((s) => {
      const st = (s.dynamic?.status || s.immutable?.status || "").toUpperCase();
      const out = (s.dynamic?.outcome_label || "").toUpperCase();
      const isTerminal =
        st.includes("WON") ||
        st.includes("LOST") ||
        st.includes("STOP") ||
        st.includes("EXP") ||
        st.includes("BREAKEVEN") ||
        st.includes("BE_") ||
        st.includes("CANCEL") ||
        out.includes("WON") ||
        out.includes("LOST") ||
        out.includes("STOPPED") ||
        out.includes("EXPIRED");
      return !isTerminal;
    });
  }, [signals]);

  // Aggregate stats derived strictly from real signals
  const { avgNetEv, avgPtp1 } = useMemo(() => {
    const targetPool = activeSignals.length > 0 ? activeSignals : signals;
    if (targetPool.length === 0) return { avgNetEv: null, avgPtp1: null };

    const netEvs = targetPool.map((s) => s.immutable.expected_net_return);
    const ptp1s = targetPool.map((s) => {
      const p = s.immutable.p_tp1;
      return p > 1.0 ? p / 100.0 : p;
    });

    const sumEv = netEvs.reduce((a, b) => a + b, 0);
    const sumP = ptp1s.reduce((a, b) => a + b, 0);

    return {
      avgNetEv: sumEv / targetPool.length,
      avgPtp1: sumP / targetPool.length,
    };
  }, [signals, activeSignals]);

  // Aggregate health records
  const healthRecords = {
    signals: signalsQuery.data?.health,
    theses: thesesQuery.data?.health,
    events: eventsQuery.data?.health,
    regime: regimeQuery.data?.health,
    intelligence: intelligenceQuery.data?.health,
  };

  const isEngineOnline =
    signalsQuery.data?.health?.status === 200 ||
    regimeQuery.data?.health?.status === 200;

  const activeThesesCount = useMemo(() => {
    if (theses.length === 0) return activeSignals.length;
    const activeTheses = theses.filter((t) => t.is_active || (t.active_signals_count && t.active_signals_count > 0));
    return activeTheses.length > 0 ? activeTheses.length : (activeSignals.length > 0 ? Math.min(activeSignals.length, theses.length) : 0);
  }, [theses, activeSignals]);

  return (
    <div className="min-h-screen bg-[#07090e] text-slate-100 p-2 sm:p-5 lg:p-6 space-y-6 relative overflow-hidden">
      {/* Ambient background light gradients */}
      <div className="absolute top-0 left-1/4 w-[600px] h-[350px] bg-cyan-600/5 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute top-1/3 right-10 w-[500px] h-[500px] bg-indigo-600/5 rounded-full blur-[160px] pointer-events-none" />
      <div className="absolute bottom-10 left-10 w-[500px] h-[400px] bg-emerald-600/5 rounded-full blur-[150px] pointer-events-none" />

      {/* 1. Header & Live API Telemetry */}
      <V16Header
        healthRecords={healthRecords}
        activeSignalsCount={activeSignals.length}
        activeThesesCount={activeThesesCount}
        regime={regimeData?.regime || "RANGE"}
      />

      {/* 2. Top KPI Metric Row */}
      <V16KpiRow
        activeSignalsCount={activeSignals.length}
        activeThesesCount={activeThesesCount}
        avgNetEv={avgNetEv}
        avgPtp1={avgPtp1}
        regime={regimeData?.regime || "RANGE"}
        isEngineOnline={isEngineOnline}
      />

      {/* 3. Qualified V16 Signals Section (Cards & Table Views) - Positioned Above Market State & Trade Theses */}
      <div className="relative z-10 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-1">
          <div>
            <div className="flex items-center gap-2">
              <span className="p-1.5 rounded-lg bg-cyan-950/60 border border-cyan-500/30 text-cyan-400">
                <Sparkles className="w-3.5 h-3.5" />
              </span>
              <h2 className="text-base font-black tracking-tight text-white font-mono uppercase">
                Qualified V16 Signal Execution Matrix
              </h2>
            </div>
            <p className="text-xs text-slate-400 font-mono mt-1">
              Filtered for positive Expected Net Return (EVnet &gt; 0%) after all exchange friction deductions
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            {/* View Mode Toggle: Cards vs Table */}
            <div className="flex items-center gap-1 p-1 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
              <button
                onClick={() => setDisplayMode("CARDS")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all ${
                  displayMode === "CARDS"
                    ? "bg-gradient-to-r from-cyan-600/30 to-indigo-600/30 text-cyan-300 border border-cyan-500/50 shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <LayoutGrid className="w-3.5 h-3.5 text-cyan-400" />
                <span>Cards View</span>
              </button>

              <button
                onClick={() => setDisplayMode("TABLE")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all ${
                  displayMode === "TABLE"
                    ? "bg-gradient-to-r from-cyan-600/30 to-indigo-600/30 text-cyan-300 border border-cyan-500/50 shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Table className="w-3.5 h-3.5 text-cyan-400" />
                <span>Table View</span>
              </button>
            </div>

            <button
              onClick={() => {
                signalsQuery.refetch();
                thesesQuery.refetch();
                eventsQuery.refetch();
                regimeQuery.refetch();
                intelligenceQuery.refetch();
              }}
              className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-800 hover:border-cyan-500/40 text-xs text-slate-300 hover:text-cyan-300 font-mono font-bold transition-all shadow-sm"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${signalsQuery.isFetching ? "animate-spin text-cyan-400" : "text-slate-400"}`} />
              <span className="hidden sm:inline">Sync Live</span>
            </button>
          </div>
        </div>

        {displayMode === "CARDS" ? (
          <V16SignalCardsGrid
            signals={signals}
            onSelectSignal={(sig) => {
              setSelectedSignal(sig);
              if (sig?.immutable?.symbol) setHudSymbol(sig.immutable.symbol);
            }}
            selectedSignalId={selectedSignal?.immutable?.signal_id}
          />
        ) : (
          <V16SignalTable
            signals={signals}
            onSelectSignal={(sig) => {
              setSelectedSignal(sig);
              if (sig?.immutable?.symbol) setHudSymbol(sig.immutable.symbol);
            }}
            selectedSignalId={selectedSignal?.immutable?.signal_id}
          />
        )}
      </div>

      {/* 4. Core Operational Intelligence Grid: Market State Regime & Trade Thesis Clusters */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 relative z-10">
        <V16RegimeCard
          regimeData={regimeData}
          isLoading={regimeQuery.isLoading}
        />
        <V16ThesisPanel
          theses={theses}
          isLoading={thesesQuery.isLoading}
        />
      </div>

      {/* 5. Institutional Macro, Fed/FOMC, Spot ETF & Whale Depth Command HUD */}
      <div className="relative z-10">
        <V16InstitutionalIntelligenceHUD
          intelligence={intelligenceData}
          isLoading={intelligenceQuery.isLoading}
          selectedSymbol={hudSymbol}
          onSymbolChange={(sym) => setHudSymbol(sym)}
          availableSymbols={Array.from(new Set(["BTC/USDT", "ETH/USDT", "SOL/USDT", "SUI/USDT", "DOGE/USDT", "AVAX/USDT", ...signals.map(s => s.immutable.symbol)])).slice(0, 10)}
          onRefresh={() => intelligenceQuery.refetch()}
        />
      </div>

      {/* 6. Performance and Event Audit Stream */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 relative z-10">
        <V16PerformancePanel signals={signals} />
        <V16EventJournal
          events={events}
          isLoading={eventsQuery.isLoading}
        />
      </div>

      {/* Signal Detail Modal */}
      <V16SignalDetailModal
        signal={selectedSignal}
        onClose={() => setSelectedSignal(null)}
      />
    </div>
  );
}
