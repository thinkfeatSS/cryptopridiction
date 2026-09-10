"use client";

import React, { useState, useMemo } from "react";
import { useForecastQuery, useLivePricesQuery } from "@/hooks/useCryptoData";
import { formatUsd } from "@/lib/utils";
import { useWatchlist } from "@/hooks/useWatchlist";
import CoinSignalHistoryModal from "@/components/CoinSignalHistoryModal";
import { Layers, Sparkles, ArrowUpRight, ArrowDownRight, Target, History, Star } from "lucide-react";

export default function RadarTable() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: livePricesData } = useLivePricesQuery();
  const livePrices = useMemo(() => livePricesData?.prices || {}, [livePricesData?.prices]);
  const { isStarred, toggleWatchlist } = useWatchlist();
  const [selectedCoin, setSelectedCoin] = useState<{ symbol: string; price?: number } | null>(null);
  const leaderboard = forecast?.scanner_leaderboard || [];

  // Always show Starred / Active Trade coins at the TOP, followed by the original algorithmic rank
  const sortedLeaderboard = useMemo(() => {
    return [...leaderboard].sort((a: any, b: any) => {
      const aStarred = isStarred(a.symbol);
      const bStarred = isStarred(b.symbol);
      if (aStarred && !bStarred) return -1;
      if (!aStarred && bStarred) return 1;
      return 0; // maintains algorithmic order within starred and unstarred groups
    });
  }, [leaderboard, isStarred]);

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      {/* Coin Historical 15M Signal Audit Modal */}
      {selectedCoin && (
        <CoinSignalHistoryModal
          symbol={selectedCoin.symbol}
          currentPrice={selectedCoin.price}
          onClose={() => setSelectedCoin(null)}
        />
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-slate-800/80 pb-4">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex flex-wrap items-center gap-2">
            🛰️ Multi-Horizon Opportunity Radar
            <span className="rounded-md bg-cyan-950 px-2 py-0.5 text-xs font-semibold text-cyan-400 border border-cyan-800">
              15M ➔ 30D Multi-Scale Alignment
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Cross-asset directional alignment & multi-scale confluence setup scanner.{" "}
            <span className="text-amber-400 font-semibold">⭐ Starred coins pinned to top.</span>{" "}
            <span className="text-cyan-400 font-semibold">Click any coin to view 15-minute historical records.</span>
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-xs text-slate-500 font-mono">
          Scanning multi-horizon opportunities across assets...
        </div>
      ) : sortedLeaderboard.length === 0 ? (
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
                <th className="py-3 px-4">🌊 Swing (1H)</th>
                <th className="py-3 px-4">🚀 Macro (24H)</th>
                <th className="py-3 px-4">🗓️ Weekly (7D)</th>
                <th className="py-3 px-4 text-right">Alignment & History</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
              {sortedLeaderboard.map((item: any, idx: number) => {
                const s = item.horizons?.scalp || {};
                const w = item.horizons?.swing || {};
                const m = item.horizons?.macro || {};
                const h7d = item.horizons?.weekly || {};
                const isTriple = item.is_triple_confluence;
                const starred = isStarred(item.symbol);

                const renderHorizonCell = (h: any) => {
                  const isLong = h.direction === "BULLISH" || h.direction === "LONG";
                  return (
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1 font-bold text-xs">
                        <span className={isLong ? "text-emerald-400" : "text-rose-400"}>
                          {isLong ? "🟢 LONG" : "🔴 SHORT"}
                        </span>
                        <span className="text-slate-400 font-mono text-[11px]">
                          ({h.conviction?.toFixed(1) || "50.0"}%)
                        </span>
                      </div>
                      <span className="text-[10px] text-slate-400 font-mono">
                        TP: {formatUsd(h.tp_price)}
                      </span>
                    </div>
                  );
                };

                const livePrice = livePrices[item.symbol] || livePrices[item.symbol.replace('/', '')] || item.current_price;

                return (
                  <tr
                    key={item.symbol || idx}
                    onClick={() => setSelectedCoin({ symbol: item.symbol, price: livePrice })}
                    className={`cursor-pointer transition-colors group ${
                      starred
                        ? "bg-amber-950/20 hover:bg-amber-950/35 border-l-2 border-l-amber-500"
                        : "hover:bg-slate-800/60"
                    }`}
                    title="Click to view 15-minute historical signal records for this coin"
                  >
                    {/* Asset */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleWatchlist(item.symbol);
                          }}
                          className="p-1 text-slate-500 hover:text-amber-400 transition-colors"
                          title={starred ? "Remove from Watchlist" : "Add to Watchlist"}
                        >
                          <Star
                            className={`h-3.5 w-3.5 ${
                              starred ? "fill-amber-400 text-amber-400" : ""
                            }`}
                          />
                        </button>
                        <div className="flex flex-col">
                          <span className="font-bold text-white text-sm group-hover:text-cyan-400 transition-colors flex items-center gap-1.5">
                            {item.symbol}
                            <History className="h-3 w-3 text-cyan-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                          </span>
                          <span className="text-xs text-cyan-400 font-mono font-semibold">
                            ({formatUsd(livePrice)})
                          </span>
                        </div>
                      </div>
                    </td>

                    {/* Scalp */}
                    <td className="py-3 px-4">{renderHorizonCell(s)}</td>

                    {/* Swing */}
                    <td className="py-3 px-4">{renderHorizonCell(w)}</td>

                    {/* Macro */}
                    <td className="py-3 px-4">{renderHorizonCell(m)}</td>

                    {/* Weekly */}
                    <td className="py-3 px-4">{renderHorizonCell(h7d)}</td>

                    {/* Alignment Badge */}
                    <td className="py-3 px-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {isTriple ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-cyan-950 px-2.5 py-1 text-[11px] font-black text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20">
                            <Sparkles className="h-3 w-3" /> TRIPLE
                          </span>
                        ) : null}
                        <span className="inline-flex items-center gap-1 rounded-lg bg-dark-900 group-hover:bg-cyan-950 px-2 py-1 text-[10px] font-semibold text-cyan-400 border border-slate-800 group-hover:border-cyan-500 transition-colors">
                          <History className="h-3 w-3" /> 15M History
                        </span>
                      </div>
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
