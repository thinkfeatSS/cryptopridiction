"use client";

import React, { useState, useEffect } from "react";
import { V16EndpointHealth } from "@/types/v16";
import { Activity, Server, Radio, Database, ChevronDown, ChevronUp, Terminal, ShieldCheck, Zap, Cpu } from "lucide-react";

interface Props {
  healthRecords: Record<string, V16EndpointHealth | undefined>;
  activeSignalsCount: number;
  activeThesesCount: number;
  regime: string;
}

export default function V16Header({
  healthRecords,
  activeSignalsCount,
  activeThesesCount,
  regime,
}: Props) {
  const [showDebug, setShowDebug] = useState(false);
  const [currentTimeUtc, setCurrentTimeUtc] = useState<string>("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTimeUtc(now.toISOString().substring(11, 19) + " UTC");
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  // Compute overall status
  const statuses = Object.values(healthRecords)
    .filter(Boolean)
    .map((h) => h?.status);
  const isAllHealthy = statuses.length > 0 && statuses.every((s) => s === 200);
  const hasError = statuses.some((s) => s === "ERR" || (typeof s === "number" && s >= 400));

  return (
    <div className="w-full relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-xl p-5 shadow-[0_8px_32px_rgba(0,0,0,0.5)]">
      {/* Background radial ambient lights */}
      <div className="absolute -top-24 -left-24 w-72 h-72 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -top-24 -right-24 w-72 h-72 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />

      <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-5">
        {/* Title & Brand */}
        <div className="flex items-center gap-4">
          <div className="relative">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-400 via-indigo-500 to-emerald-400 p-[2px] shadow-[0_0_20px_rgba(6,182,212,0.35)]">
              <div className="w-full h-full bg-[#0a0f1d] rounded-[10px] flex items-center justify-center">
                <span className="font-mono font-black text-base tracking-wider bg-gradient-to-r from-cyan-300 via-teal-200 to-emerald-300 bg-clip-text text-transparent">
                  V16
                </span>
              </div>
            </div>
            {/* Pulsing beacon node */}
            <span className="absolute -top-1 -right-1 flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-cyan-500 border border-slate-900" />
            </span>
          </div>

          <div>
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-2xl font-black tracking-tight text-white flex items-center gap-2">
                QUANT EDGE{" "}
                <span className="font-mono bg-gradient-to-r from-cyan-400 to-indigo-400 bg-clip-text text-transparent drop-shadow-[0_0_12px_rgba(6,182,212,0.4)]">
                  V16.0
                </span>
              </h1>
              <span className="text-[10px] font-mono font-bold tracking-widest uppercase px-2.5 py-0.5 rounded-full bg-cyan-950/60 text-cyan-300 border border-cyan-500/30 shadow-[0_0_10px_rgba(6,182,212,0.2)]">
                INSTITUTIONAL TERMINAL
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-emerald-950/50 text-emerald-400 border border-emerald-500/30 hidden sm:inline-flex items-center gap-1">
                <ShieldCheck className="w-3 h-3 text-emerald-400" />
                ZERO FABRICATION GUARANTEE
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 flex items-center gap-2">
              <span>Statistically Validated • Cost-Aware (EVnet &gt; 0%) • Risk-Controlled Execution Engine</span>
              {currentTimeUtc && (
                <span className="font-mono text-slate-500 hidden md:inline">
                  • <span className="text-slate-400">{currentTimeUtc}</span>
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Live System Health Indicators */}
        <div className="flex flex-wrap items-center gap-2.5 text-xs">
          {/* V16 Engine State */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950/70 border border-slate-800 font-mono shadow-sm">
            <span className="relative flex h-2.5 w-2.5">
              {isAllHealthy && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              )}
              <span
                className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                  isAllHealthy
                    ? "bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)]"
                    : hasError
                    ? "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.8)]"
                    : "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]"
                }`}
              />
            </span>
            <span className="text-slate-300">
              V16 ENGINE:{" "}
              <strong
                className={
                  isAllHealthy ? "text-emerald-400" : hasError ? "text-rose-400" : "text-amber-400"
                }
              >
                {isAllHealthy ? "ONLINE" : hasError ? "DEGRADED" : "SYNCING"}
              </strong>
            </span>
          </div>

          {/* Scanner State */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950/70 border border-slate-800 font-mono shadow-sm">
            <Radio className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span className="text-slate-300">
              SCANNER: <strong className="text-cyan-400">ACTIVE (110 COINS)</strong>
            </span>
          </div>

          {/* Regime Badge */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950/70 border border-slate-800 font-mono shadow-sm">
            <Activity className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-slate-300">
              REGIME: <strong className="text-indigo-300">{regime || "RANGE"}</strong>
            </span>
          </div>

          {/* Telemetry Toggle */}
          <button
            onClick={() => setShowDebug(!showDebug)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 hover:text-white border border-slate-700 font-mono text-[11px] transition-all duration-200 shadow-sm"
            title="Inspect V16 Backend Endpoints Telemetry"
          >
            <Terminal className="w-3.5 h-3.5 text-cyan-400" />
            <span>API Telemetry</span>
            {showDebug ? <ChevronUp className="w-3 h-3 text-slate-400" /> : <ChevronDown className="w-3 h-3 text-slate-400" />}
          </button>
        </div>
      </div>

      {/* Expanded API Telemetry Panel */}
      {showDebug && (
        <div className="mt-5 pt-4 border-t border-slate-800/80 text-xs font-mono relative z-10 animate-fadeIn">
          <div className="text-[11px] uppercase tracking-wider text-slate-400 mb-3 font-bold flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Server className="w-3.5 h-3.5 text-cyan-400" />
              <span>Production Endpoint Telemetry & Latencies (Live Backend)</span>
            </span>
            <span className="text-[10px] text-slate-500 lowercase">
              Auto-refreshed with queries
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {Object.entries(healthRecords).map(([key, record]) => {
              if (!record) return null;
              const isOk = record.status === 200;
              return (
                <div
                  key={key}
                  className={`p-3 rounded-xl border backdrop-blur-md transition-all ${
                    isOk
                      ? "bg-slate-950/70 border-slate-800 hover:border-cyan-500/30 text-slate-300"
                      : "bg-rose-950/30 border-rose-800/40 text-rose-300"
                  }`}
                >
                  <div className="flex items-center justify-between font-bold">
                    <span className="text-slate-200 text-xs truncate" title={record.endpoint}>
                      {record.endpoint}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                        isOk
                          ? "bg-emerald-950/80 text-emerald-400 border border-emerald-500/30"
                          : "bg-rose-950/80 text-rose-400 border border-rose-500/30"
                      }`}
                    >
                      {record.status}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                    <span>Latency: <strong className="text-cyan-300">{record.latencyMs} ms</strong></span>
                    <span>Items: <strong className="text-white">{record.itemCount}</strong></span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-1 truncate">
                    Updated: {record.lastUpdated}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
