"use client";

import React from "react";
import { useForecastQuery } from "@/hooks/useCryptoData";
import { formatUsd } from "@/lib/utils";
import { Layers, Sparkles, ArrowUpRight, ArrowDownRight, Target } from "lucide-react";

export default function RadarTable() {
  const { data: forecast, isLoading } = useForecastQuery();
  const leaderboard = forecast?.scanner_leaderboard || [];

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            🛰️ Multi-Horizon Opportunity Radar
            <span className="rounded-md bg-cyan-950 px-2 py-0.5 text-xs font-semibold text-cyan-400 border border-cyan-800">
              Minutes (15M) | Hours (1H) | Days (24H)
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Cross-asset directional alignment & triple confluence setup scanner
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-xs text-slate-500 font-mono">
          Scanning multi-horizon opportunities across assets...
        </div>
      ) : leaderboard.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-500 font-sans">
          No scanner results available for this round.
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800/80">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Asset & Live Price</th>
                <th className="py-3 px-4">⚡ Scalp (15M)</th>
                <th className="py-3 px-4">🌊 Swing (1H-2H)</th>
                <th className="py-3 px-4">🚀 Macro (24H)</th>
                <th className="py-3 px-4 text-right">Alignment</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
              {leaderboard.map((item: any, idx: number) => {
                const s = item.horizons?.scalp || {};
                const w = item.horizons?.swing || {};
                const m = item.horizons?.macro || {};
                const isTriple = item.is_triple_confluence;

                const renderHorizonCell = (h: any) => {
                  const isLong = h.direction === "BULLISH" || h.direction === "LONG";
                  return (
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1 font-bold text-xs">
                        <span className={isLong ? "text-emerald-400" : "text-rose-400"}>
                          {isLong ? "🟢 LONG" : "🔴 SHORT"}
                        </span>
                        <span className="text-slate-400 font-mono text-[11px]">
                          ({h.conviction?.toFixed(1)}%)
                        </span>
                      </div>
                      <span className="text-[10px] text-slate-400 font-mono">
                        TP: {formatUsd(h.tp_price)} | SL: {formatUsd(h.sl_price)}
                      </span>
                    </div>
                  );
                };

                return (
                  <tr key={item.symbol || idx} className="hover:bg-slate-800/40 transition-colors">
                    {/* Asset */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-bold text-white text-sm">{item.symbol}</span>
                        <span className="text-xs text-cyan-400 font-mono font-semibold">
                          {formatUsd(item.current_price)}
                        </span>
                      </div>
                    </td>

                    {/* Scalp */}
                    <td className="py-3 px-4">{renderHorizonCell(s)}</td>

                    {/* Swing */}
                    <td className="py-3 px-4">{renderHorizonCell(w)}</td>

                    {/* Macro */}
                    <td className="py-3 px-4">{renderHorizonCell(m)}</td>

                    {/* Alignment Badge */}
                    <td className="py-3 px-4 text-right">
                      {isTriple ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-cyan-950 px-2.5 py-1 text-[11px] font-black text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20">
                          <Sparkles className="h-3 w-3" /> TRIPLE BUY
                        </span>
                      ) : (
                        <span className="text-[11px] text-slate-500 font-mono">
                          Independent
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
