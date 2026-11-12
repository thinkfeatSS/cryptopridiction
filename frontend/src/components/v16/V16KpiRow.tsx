"use client";

import React from "react";
import { formatPercent, formatProbability } from "@/lib/utils/v16";
import { Target, Layers, TrendingUp, Shield, Cpu, Activity, Zap } from "lucide-react";

interface Props {
  activeSignalsCount: number;
  totalSignalsCount?: number;
  activeThesesCount: number;
  avgNetEv: number | null;
  avgPtp1: number | null;
  regime: string;
  isEngineOnline: boolean;
}

export default function V16KpiRow({
  activeSignalsCount,
  totalSignalsCount,
  activeThesesCount,
  avgNetEv,
  avgPtp1,
  regime,
  isEngineOnline,
}: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
      {/* KPI 1: Active Qualified Signals */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-4 transition-all duration-300 hover:border-cyan-500/40 hover:shadow-[0_8px_25px_rgba(6,182,212,0.12)] group">
        <div className="absolute top-0 right-0 w-24 h-24 bg-cyan-500/5 rounded-full blur-xl group-hover:bg-cyan-500/10 transition-colors pointer-events-none" />
        <div className="flex items-center justify-between text-slate-400 text-[11px] font-mono font-bold tracking-wider">
          <span>ACTIVE SIGNALS</span>
          <div className="p-1.5 rounded-lg bg-cyan-950/60 border border-cyan-500/30 text-cyan-400">
            <Target className="w-3.5 h-3.5" />
          </div>
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-3xl font-black font-mono tracking-tight text-white">{activeSignalsCount}</span>
          <span className="text-[10px] text-cyan-400 font-mono font-bold">V16 QUALIFIED</span>
        </div>
        <div className="text-[10px] text-slate-400 mt-1 flex items-center justify-between">
          <span>{totalSignalsCount !== undefined ? `${activeSignalsCount} Active / ${totalSignalsCount} Total` : "Zero Invalid Rates"}</span>
          <span className="text-emerald-400 font-mono">100% Guarded</span>
        </div>
      </div>

      {/* KPI 2: Active Trade Theses */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-4 transition-all duration-300 hover:border-amber-500/40 hover:shadow-[0_8px_25px_rgba(251,191,36,0.12)] group">
        <div className="absolute top-0 right-0 w-24 h-24 bg-amber-500/5 rounded-full blur-xl group-hover:bg-amber-500/10 transition-colors pointer-events-none" />
        <div className="flex items-center justify-between text-slate-400 text-[11px] font-mono font-bold tracking-wider">
          <span>ACTIVE THESES</span>
          <div className="p-1.5 rounded-lg bg-amber-950/60 border border-amber-500/30 text-amber-400">
            <Layers className="w-3.5 h-3.5" />
          </div>
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-3xl font-black font-mono tracking-tight text-amber-300">{activeThesesCount}</span>
          <span className="text-[10px] text-amber-400/90 font-mono font-bold">CLUSTERED</span>
        </div>
        <div className="text-[10px] text-slate-400 mt-1 flex items-center justify-between">
          <span>1 Pos / Thesis Cap</span>
          <span className="text-amber-400 font-mono">Sec. 25</span>
        </div>
      </div>

      {/* KPI 3: Avg Net Expected Value */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-4 transition-all duration-300 hover:border-emerald-500/40 hover:shadow-[0_8px_25px_rgba(16,185,129,0.12)] group">
        <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-500/5 rounded-full blur-xl group-hover:bg-emerald-500/10 transition-colors pointer-events-none" />
        <div className="flex items-center justify-between text-slate-400 text-[11px] font-mono font-bold tracking-wider">
          <span>AVG NET EV</span>
          <div className="p-1.5 rounded-lg bg-emerald-950/60 border border-emerald-500/30 text-emerald-400">
            <TrendingUp className="w-3.5 h-3.5" />
          </div>
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-3xl font-black font-mono tracking-tight text-emerald-400">
            {avgNetEv !== null ? formatPercent(avgNetEv) : "—"}
          </span>
          <span className="text-[10px] text-emerald-400/90 font-mono font-bold">POST-COST</span>
        </div>
        <div className="text-[10px] text-slate-400 mt-1 flex items-center justify-between">
          <span>{activeSignalsCount > 0 ? "Active Setups EV" : "Frictions Deducted"}</span>
          <span className="text-emerald-400 font-mono">EV &gt; 0%</span>
        </div>
      </div>

      {/* KPI 4: Avg Calibrated P(TP1) */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-4 transition-all duration-300 hover:border-indigo-500/40 hover:shadow-[0_8px_25px_rgba(99,102,241,0.12)] group">
        <div className="absolute top-0 right-0 w-24 h-24 bg-indigo-500/5 rounded-full blur-xl group-hover:bg-indigo-500/10 transition-colors pointer-events-none" />
        <div className="flex items-center justify-between text-slate-400 text-[11px] font-mono font-bold tracking-wider">
          <span>AVG P(TP1)</span>
          <div className="p-1.5 rounded-lg bg-indigo-950/60 border border-indigo-500/30 text-indigo-400">
            <Activity className="w-3.5 h-3.5" />
          </div>
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-3xl font-black font-mono tracking-tight text-indigo-300">
            {avgPtp1 !== null ? formatProbability(avgPtp1) : "—"}
          </span>
          <span className="text-[10px] text-indigo-400 font-mono font-bold">CALIBRATED</span>
        </div>
        <div className="text-[10px] text-slate-400 mt-1 flex items-center justify-between">
          <span>{activeSignalsCount > 0 ? "Active Calibrated" : "Platt / Isotonic"}</span>
          <span className="text-indigo-400 font-mono">ECE ≤ 0.12</span>
        </div>
      </div>

      {/* KPI 5: Market Regime */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-4 transition-all duration-300 hover:border-purple-500/40 hover:shadow-[0_8px_25px_rgba(168,85,247,0.12)] group">
        <div className="absolute top-0 right-0 w-24 h-24 bg-purple-500/5 rounded-full blur-xl group-hover:bg-purple-500/10 transition-colors pointer-events-none" />
        <div className="flex items-center justify-between text-slate-400 text-[11px] font-mono font-bold tracking-wider">
          <span>MARKET REGIME</span>
          <div className="p-1.5 rounded-lg bg-purple-950/60 border border-purple-500/30 text-purple-400">
            <Shield className="w-3.5 h-3.5" />
          </div>
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-2xl font-black font-mono tracking-tight text-white truncate">
            {regime || "RANGE"}
          </span>
        </div>
        <div className="text-[10px] text-slate-400 mt-1 flex items-center justify-between">
          <span>9-State Classifier</span>
          <span className="text-purple-400 font-mono">Sec. 28-29</span>
        </div>
      </div>

      {/* KPI 6: V16 Platform Status */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-4 transition-all duration-300 hover:border-teal-500/40 hover:shadow-[0_8px_25px_rgba(20,184,166,0.12)] group">
        <div className="absolute top-0 right-0 w-24 h-24 bg-teal-500/5 rounded-full blur-xl group-hover:bg-teal-500/10 transition-colors pointer-events-none" />
        <div className="flex items-center justify-between text-slate-400 text-[11px] font-mono font-bold tracking-wider">
          <span>V16 ENGINE</span>
          <div className="p-1.5 rounded-lg bg-teal-950/60 border border-teal-500/30 text-teal-400">
            <Cpu className="w-3.5 h-3.5" />
          </div>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span className="relative flex h-3 w-3">
            {isEngineOnline && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            )}
            <span
              className={`relative inline-flex rounded-full h-3 w-3 ${
                isEngineOnline ? "bg-emerald-400" : "bg-rose-500"
              }`}
            />
          </span>
          <span className="text-2xl font-black font-mono tracking-tight text-white">
            {isEngineOnline ? "ONLINE" : "OFFLINE"}
          </span>
        </div>
        <div className="text-[10px] text-slate-400 mt-1 flex items-center justify-between">
          <span>Institutional Mode</span>
          <span className="text-emerald-400 font-mono">Daemon 24/7</span>
        </div>
      </div>
    </div>
  );
}
