"use client";

import React, { useState, useMemo } from "react";
import { useForecastQuery, useLivePricesQuery } from "@/hooks/useCryptoData";
import { formatUsd } from "@/lib/utils";
import { useWatchlist } from "@/hooks/useWatchlist";
import CoinSignalHistoryModal from "@/components/CoinSignalHistoryModal";
import {
  Star,
  Sparkles,
  ArrowUpRight,
  ArrowDownRight,
  Target,
  History,
  ShieldAlert,
  Search,
  CheckCircle2,
  AlertTriangle,
  Flame,
  Zap,
} from "lucide-react";

export default function StarredRadarTable() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: livePricesData } = useLivePricesQuery();
  const livePrices = useMemo(() => livePricesData?.prices || {}, [livePricesData?.prices]);
  const { watchlist, isStarred, toggleWatchlist, isLoaded } = useWatchlist();
  const [selectedCoin, setSelectedCoin] = useState<{ symbol: string; price?: number } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const leaderboard = forecast?.scanner_leaderboard || [];

  // Filter leaderboard to only include coins that are in the user's starred watchlist
  const starredItems = useMemo(() => {
    return leaderboard.filter((item: any) => {
      if (!isStarred(item.symbol)) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        return item.symbol.toLowerCase().includes(q);
      }
      return true;
    });
  }, [leaderboard, isStarred, searchQuery]);

  // Quick preset coins to suggest if watchlist is empty
  const suggestedCoins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"];

  return (
    <div className="glass-panel rounded-2xl p-5 border border-amber-500/30 shadow-xl shadow-amber-950/10">
      {/* Coin Historical 15M Signal Audit Modal */}
      {selectedCoin && (
        <CoinSignalHistoryModal
          symbol={selectedCoin.symbol}
          currentPrice={selectedCoin.price}
          onClose={() => setSelectedCoin(null)}
        />
      )}

      {/* Header */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-amber-500/20 text-amber-400 border border-amber-500/40 shadow-sm">
              <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
            </span>
            <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
              Starred & Active Trades Monitor Radar
            </h2>
            <span className="rounded-md bg-amber-950/80 px-2.5 py-0.5 text-xs font-bold text-amber-300 border border-amber-600/40">
              ⭐ {watchlist.length} Active {watchlist.length === 1 ? "Position" : "Positions"}
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Real-time multi-horizon health, invalidations, and trend alignment for your starred crypto trades.
          </p>
        </div>

        {/* Search / Filter */}
        {watchlist.length > 0 && (
          <div className="relative min-w-[200px]">
            <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-500" />
            <input
              type="text"
              placeholder="Filter starred coins..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-xl bg-dark-950/80 pl-8 pr-3 py-1.5 text-xs text-slate-200 border border-slate-800 focus:border-amber-500 focus:outline-none placeholder-slate-600"
            />
          </div>
        )}
      </div>

      {isLoading || !isLoaded ? (
        <div className="py-12 text-center text-xs text-slate-500 font-mono">
          Loading active trade telemetry across horizons...
        </div>
      ) : watchlist.length === 0 ? (
        /* Empty State */
        <div className="py-10 text-center space-y-4">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Star className="h-6 w-6 text-amber-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">No Starred Coins in Active Monitor</h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto mt-1">
              Click the <strong className="text-amber-400">⭐ star icon</strong> next to any coin in the terminal to monitor its multi-horizon alignment, Take-Profit targets, and invalidations in real-time.
            </p>
          </div>

          {/* Quick Add Presets */}
          <div className="pt-2">
            <span className="text-[11px] uppercase tracking-wider font-bold text-slate-500 font-mono">
              Quick Star Popular Assets:
            </span>
            <div className="flex flex-wrap items-center justify-center gap-2 mt-2">
              {suggestedCoins.map((sym) => (
                <button
                  key={sym}
                  onClick={() => toggleWatchlist(sym)}
                  className="flex items-center gap-1 rounded-lg bg-dark-900 px-2.5 py-1 text-xs font-semibold text-slate-300 border border-slate-800 hover:border-amber-500/50 hover:text-amber-300 transition-colors"
                >
                  <Star className="h-3 w-3 text-amber-400" /> {sym}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : starredItems.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-500 font-sans">
          No starred coins matching &quot;{searchQuery}&quot;.
        </div>
      ) : (
        /* Active Starred Trades Radar Table */
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800/80">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Monitored Asset & Price</th>
                <th className="py-3 px-4">⚡ Scalp (15M)</th>
                <th className="py-3 px-4">🌊 Swing (1H)</th>
                <th className="py-3 px-4">🚀 Macro (24H)</th>
                <th className="py-3 px-4">🗓️ Weekly (7D)</th>
                <th className="py-3 px-4 text-center">Horizon Confluence Status</th>
                <th className="py-3 px-4 text-right">Audit & History</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
              {starredItems.map((item: any, idx: number) => {
                const s = item.horizons?.scalp || {};
                const w = item.horizons?.swing || {};
                const m = item.horizons?.macro || {};
                const h7d = item.horizons?.weekly || {};

                // Determine Horizon Confluence
                const directions = [
                  s.direction || "",
                  w.direction || "",
                  m.direction || "",
                  h7d.direction || "",
                ].map((d) => (d.includes("LONG") || d.includes("BULL") ? "LONG" : "SHORT"));

                const longCount = directions.filter((d) => d === "LONG").length;
                const shortCount = directions.filter((d) => d === "SHORT").length;

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
                    className="hover:bg-slate-800/60 cursor-pointer transition-colors group"
                    title="Click to view 15-minute historical signal records for this coin"
                  >
                    {/* Asset & Star */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2.5">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleWatchlist(item.symbol);
                          }}
                          className="p-1 rounded text-amber-400 hover:text-slate-400 transition-colors"
                          title="Unstar / Remove from active monitor"
                        >
                          <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
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

                    {/* Confluence Badge */}
                    <td className="py-3 px-4 text-center">
                      {longCount === 4 ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-950/80 px-2.5 py-1 text-[11px] font-black text-emerald-300 border border-emerald-500/50 shadow-sm shadow-emerald-500/20">
                          <CheckCircle2 className="h-3 w-3" /> FULL BULL (4/4)
                        </span>
                      ) : shortCount === 4 ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-rose-950/80 px-2.5 py-1 text-[11px] font-black text-rose-300 border border-rose-500/50 shadow-sm shadow-rose-500/20">
                          <CheckCircle2 className="h-3 w-3" /> FULL BEAR (4/4)
                        </span>
                      ) : longCount >= 3 ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-950/40 px-2 py-0.5 text-[10px] font-bold text-emerald-400 border border-emerald-600/30">
                          🟢 BULL ALIGNED ({longCount}/4)
                        </span>
                      ) : shortCount >= 3 ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-rose-950/40 px-2 py-0.5 text-[10px] font-bold text-rose-400 border border-rose-600/30">
                          🔴 BEAR ALIGNED ({shortCount}/4)
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-950/40 px-2 py-0.5 text-[10px] font-bold text-amber-400 border border-amber-600/30">
                          <AlertTriangle className="h-3 w-3" /> MIXED / HEDGE (2/2)
                        </span>
                      )}
                    </td>

                    {/* 15M History CTA */}
                    <td className="py-3 px-4 text-right">
                      <span className="inline-flex items-center gap-1 rounded-lg bg-dark-900 group-hover:bg-cyan-950 px-2.5 py-1 text-[11px] font-semibold text-cyan-400 border border-slate-800 group-hover:border-cyan-500 transition-colors">
                        <History className="h-3 w-3" /> 15M History
                      </span>
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
