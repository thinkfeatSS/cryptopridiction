"use client";

import React, { useState, useEffect } from "react";
import { useForecastQuery, useStatusQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd, formatTimeRemaining } from "@/lib/utils";
import {
  Sparkles,
  Radio,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Layers,
  Search,
  Zap,
  Target,
  ShieldAlert,
} from "lucide-react";

export default function AssetPredictionMatrix() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: status } = useStatusQuery();
  const [selectedHorizon, setSelectedHorizon] = useState<"all" | "scalp" | "swing" | "macro">("all");
  const [search, setSearch] = useState("");
  const [localSeconds, setLocalSeconds] = useState<number>(0);

  const leaderboard = forecast?.scanner_leaderboard || [];

  // Countdown timer synchronization
  useEffect(() => {
    if (status?.seconds_to_next_scan !== undefined) {
      setLocalSeconds(status.seconds_to_next_scan);
    }
  }, [status?.seconds_to_next_scan]);

  useEffect(() => {
    const timer = setInterval(() => {
      setLocalSeconds((prev) => (prev > 0 ? prev - 1 : 900));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const filteredAssets = leaderboard.filter((item: any) => {
    if (!search) return true;
    return item.symbol.toLowerCase().includes(search.toLowerCase().trim());
  });

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      {/* Header with Live 15-Minute Scan Countdown */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between border-b border-slate-800/80 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
              <Zap className="h-5 w-5 text-cyan-400" />
              Complete 25-Asset Market Prediction Matrix
            </h2>
            <span className="rounded-md bg-dark-900 px-2 py-0.5 text-xs font-semibold text-cyan-300 border border-cyan-700/50">
              {leaderboard.length} Assets Scanned
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Multi-horizon AI predictions, entry prices, 1:2 R:R targets, and confluence grading across 25 crypto assets
          </p>
        </div>

        {/* Live Refresh Timer Ring */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2.5 rounded-xl border border-cyan-500/40 bg-cyan-950/40 px-3.5 py-2 text-xs shadow-lg shadow-cyan-500/10">
            <div className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400 opacity-75"></span>
              <span className="relative inline-flex h-3 w-3 rounded-full bg-cyan-500"></span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] uppercase font-bold tracking-wider text-cyan-300">
                Next AI Scan & Refresh In
              </span>
              <span className="font-mono text-sm font-black text-white">
                {formatTimeRemaining(localSeconds)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Controls & Horizon Tabs */}
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Horizon Filter Tabs */}
        <div className="flex items-center gap-1 rounded-xl bg-dark-900/90 p-1 border border-slate-800">
          <button
            onClick={() => setSelectedHorizon("all")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              selectedHorizon === "all"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            All Horizons
          </button>
          <button
            onClick={() => setSelectedHorizon("scalp")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              selectedHorizon === "scalp"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            ⚡ Scalp (15M)
          </button>
          <button
            onClick={() => setSelectedHorizon("swing")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              selectedHorizon === "swing"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            🌊 Swing (1H)
          </button>
          <button
            onClick={() => setSelectedHorizon("macro")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              selectedHorizon === "macro"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            🚀 Macro (24H)
          </button>
        </div>

        {/* Search Bar */}
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search from 25 assets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-xl bg-dark-900/90 pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 border border-slate-800 focus:border-cyan-500 focus:outline-none"
          />
        </div>
      </div>

      {/* 25 Assets Full Prediction Table */}
      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800/80">
        <table className="w-full text-left text-xs text-slate-300 font-mono">
          <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="py-3 px-4"># / Asset & Live Price</th>
              {selectedHorizon === "all" ? (
                <>
                  <th className="py-3 px-4">⚡ Scalp (15M) Setup</th>
                  <th className="py-3 px-4">🌊 Swing (1H) Setup</th>
                  <th className="py-3 px-4">🚀 Macro (24H) Setup</th>
                  <th className="py-3 px-4 text-right">Triple Alignment</th>
                </>
              ) : (
                <>
                  <th className="py-3 px-4">Predicted Direction</th>
                  <th className="py-3 px-4">Conviction %</th>
                  <th className="py-3 px-4">Take-Profit Target</th>
                  <th className="py-3 px-4">Invalidation SL</th>
                  <th className="py-3 px-4">Expected Return</th>
                  <th className="py-3 px-4 text-right">Actionable Decision</th>
                </>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-slate-500 font-sans">
                  Loading 25 asset predictions from latest scan...
                </td>
              </tr>
            ) : filteredAssets.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-slate-500 font-sans">
                  No assets match your search.
                </td>
              </tr>
            ) : (
              filteredAssets.map((item: any, idx: number) => {
                const s = item.horizons?.scalp || {};
                const w = item.horizons?.swing || {};
                const m = item.horizons?.macro || {};
                const isTriple = item.is_triple_confluence;

                // Specific Horizon View
                if (selectedHorizon !== "all") {
                  const h = item.horizons?.[selectedHorizon] || {};
                  const isLong = h.direction === "BULLISH" || h.direction === "LONG";
                  const conv = h.conviction ?? 50.0;
                  const expRet = h.exp_return ? h.exp_return * 100 : 0.0;

                  return (
                    <tr key={item.symbol} className="hover:bg-slate-800/40 transition-colors">
                      {/* Asset & Price */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-500 font-sans text-xs">#{idx + 1}</span>
                          <div>
                            <span className="font-bold text-white text-sm font-sans">{item.symbol}</span>
                            <p className="text-cyan-400 font-semibold">{formatUsd(item.current_price)}</p>
                          </div>
                        </div>
                      </td>

                      {/* Direction */}
                      <td className="py-3 px-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-bold font-sans ${
                            isLong
                              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                              : "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                          }`}
                        >
                          {isLong ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                          {isLong ? "LONG BUY" : "SHORT SELL"}
                        </span>
                      </td>

                      {/* Conviction */}
                      <td className="py-3 px-4">
                        <span className="font-bold text-cyan-300">{conv.toFixed(1)}%</span>
                      </td>

                      {/* Take Profit */}
                      <td className="py-3 px-4 font-bold text-emerald-400">
                        {formatUsd(h.tp_price)}
                      </td>

                      {/* Stop Loss */}
                      <td className="py-3 px-4 font-bold text-rose-400">
                        {formatUsd(h.sl_price)}
                      </td>

                      {/* Exp Return */}
                      <td className="py-3 px-4">
                        <span className={`font-bold ${expRet >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {formatPercent(expRet)}
                        </span>
                      </td>

                      {/* Decision */}
                      <td className="py-3 px-4 text-right font-sans">
                        <span className="rounded-lg bg-dark-900 px-2.5 py-1 text-[11px] font-semibold text-slate-200 border border-slate-800">
                          {h.decision || "MONITOR CHOP"}
                        </span>
                      </td>
                    </tr>
                  );
                }

                // All-Horizon Combined Row
                return (
                  <tr key={item.symbol} className="hover:bg-slate-800/40 transition-colors">
                    {/* Asset & Price */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-500 font-sans text-xs">#{idx + 1}</span>
                        <div>
                          <span className="font-bold text-white text-sm font-sans">{item.symbol}</span>
                          <p className="text-cyan-400 font-semibold">{formatUsd(item.current_price)}</p>
                        </div>
                      </div>
                    </td>

                    {/* Scalp (15M) */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col text-xs">
                        <span className={s.direction === "BULLISH" ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                          {s.direction === "BULLISH" ? "🟢 LONG" : "🔴 SHORT"} ({s.conviction?.toFixed(1)}%)
                        </span>
                        <span className="text-[10px] text-slate-400">
                          TP: {formatUsd(s.tp_price)} | SL: {formatUsd(s.sl_price)}
                        </span>
                      </div>
                    </td>

                    {/* Swing (1H) */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col text-xs">
                        <span className={w.direction === "BULLISH" ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                          {w.direction === "BULLISH" ? "🟢 LONG" : "🔴 SHORT"} ({w.conviction?.toFixed(1)}%)
                        </span>
                        <span className="text-[10px] text-slate-400">
                          TP: {formatUsd(w.tp_price)} | SL: {formatUsd(w.sl_price)}
                        </span>
                      </div>
                    </td>

                    {/* Macro (24H) */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col text-xs">
                        <span className={m.direction === "BULLISH" ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                          {m.direction === "BULLISH" ? "🟢 LONG" : "🔴 SHORT"} ({m.conviction?.toFixed(1)}%)
                        </span>
                        <span className="text-[10px] text-slate-400">
                          TP: {formatUsd(m.tp_price)} | SL: {formatUsd(m.sl_price)}
                        </span>
                      </div>
                    </td>

                    {/* Triple Confluence Badge */}
                    <td className="py-3 px-4 text-right font-sans">
                      {isTriple ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-cyan-950 px-2.5 py-1 text-[11px] font-black text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20">
                          <Sparkles className="h-3 w-3" /> TRIPLE BUY
                        </span>
                      ) : (
                        <span className="text-[11px] text-slate-500">Independent</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
