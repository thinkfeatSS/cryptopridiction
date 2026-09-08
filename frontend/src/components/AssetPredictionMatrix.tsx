"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useForecastQuery, useStatusQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd } from "@/lib/utils";
import CoinSignalHistoryModal from "@/components/CoinSignalHistoryModal";
import ScanCountdownBadge from "@/components/ScanCountdownBadge";
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
  History,
  CheckCircle2,
  XCircle,
  Hourglass,
} from "lucide-react";

type HorizonKey = "all" | "watchlist" | "scalp" | "swing" | "macro" | "horizon_2d" | "horizon_3d" | "weekly" | "biweekly" | "monthly";

import { useWatchlist } from "@/hooks/useWatchlist";
import { Star } from "lucide-react";

// Helper to render rich 3-line signal strength and catalyst badges matching institutional scanner
function renderSignalCell(h?: any) {
  if (!h || (!h.direction && !h.decision)) {
    return <span className="text-slate-600 font-sans text-xs">—</span>;
  }

  const isLong = h.direction === "BULLISH" || h.direction === "LONG" || (h.decision && h.decision.includes("LONG"));
  const directionText = h.direction || (isLong ? "BULLISH" : "BEARISH");
  const convictionVal = h.conviction !== undefined && h.conviction !== null ? Number(h.conviction).toFixed(1) : "—";

  let decision: string = h.decision || (isLong ? "EXECUTE LONG" : "EXECUTE SHORT");
  // Ensure appropriate prefix emoji if missing
  if (
    !decision.startsWith("🎯") &&
    !decision.startsWith("⛔") &&
    !decision.startsWith("✅") &&
    !decision.startsWith("⚡") &&
    !decision.startsWith("🌊") &&
    !decision.startsWith("💎")
  ) {
    if (decision.includes("FILTER")) {
      decision = `⛔ ${decision}`;
    } else if (decision.includes("ELITE")) {
      decision = `🎯 ${decision}`;
    } else if (decision.includes("STANDARD")) {
      decision = `✅ ${decision}`;
    } else if (decision.includes("SHORT SQUEEZE")) {
      decision = `⚡ ${decision}`;
    } else if (decision.includes("LONG FLUSH")) {
      decision = `🌊 ${decision}`;
    } else {
      decision = `${isLong ? "🟢" : "🔴"} ${decision}`;
    }
  }

  const isFilter = decision.includes("FILTER");
  const isShortSqueeze = decision.includes("SHORT SQUEEZE");
  const isLongFlush = decision.includes("LONG FLUSH");
  const isLiquiditySweep = decision.includes("LIQUIDITY-SWEEP") || decision.includes("SWEEP");
  const isDipBuy = decision.includes("DIP-BUY");
  const isRallySell = decision.includes("RALLY-SELL");
  const isElite = decision.includes("ELITE");

  let badgeStyle = "bg-dark-900 text-slate-300 border-slate-800";
  if (isFilter) {
    badgeStyle = "bg-slate-900/90 text-slate-400 border-slate-800/80";
  } else if (isShortSqueeze) {
    badgeStyle = "bg-amber-950/80 text-amber-300 border-amber-500/60 shadow-sm shadow-amber-500/20";
  } else if (isLongFlush) {
    badgeStyle = "bg-purple-950/80 text-purple-300 border-purple-500/60 shadow-sm shadow-purple-500/20";
  } else if (isDipBuy) {
    badgeStyle = "bg-emerald-950/90 text-emerald-300 border-emerald-500/70 shadow-sm shadow-emerald-500/20";
  } else if (isRallySell) {
    badgeStyle = "bg-rose-950/90 text-rose-300 border-rose-500/70 shadow-sm shadow-rose-500/20";
  } else if (isLiquiditySweep) {
    badgeStyle = isLong
      ? "bg-cyan-950/90 text-cyan-300 border-cyan-500/70 shadow-sm shadow-cyan-500/20"
      : "bg-fuchsia-950/90 text-fuchsia-300 border-fuchsia-500/70 shadow-sm shadow-fuchsia-500/20";
  } else if (isElite) {
    badgeStyle = isLong
      ? "bg-emerald-950/80 text-emerald-300 border-emerald-500/70 shadow-sm shadow-emerald-500/20"
      : "bg-rose-950/80 text-rose-300 border-rose-500/70 shadow-sm shadow-rose-500/20";
  } else if (isLong) {
    badgeStyle = "bg-emerald-950/50 text-emerald-400 border-emerald-800/60";
  } else {
    badgeStyle = "bg-rose-950/50 text-rose-400 border-rose-800/60";
  }

  return (
    <div className="flex flex-col gap-1 py-1 min-w-[170px] max-w-[240px]">
      {/* Line 1: Direction & Conviction % (e.g. 🔴 BEARISH (75.7%) / 🟢 BULLISH (82.1%)) */}
      <div className="flex items-center gap-1.5 font-bold font-mono text-[11px] leading-tight">
        <span>{isLong ? "🟢" : "🔴"}</span>
        <span className={isLong ? "text-emerald-400 font-extrabold" : "text-rose-400 font-extrabold"}>
          {directionText}
        </span>
        <span className="text-slate-300 font-medium">({convictionVal}%)</span>
      </div>

      {/* Line 2: Take Profit & Stop Loss targets (e.g. TP: $0.007787 | SL: $0.008197) */}
      <div className="text-[10px] font-mono text-slate-400 whitespace-nowrap leading-tight">
        <span>TP: <strong className="text-emerald-400">{formatUsd(h.tp_price)}</strong></span>
        <span className="mx-1 text-slate-600">|</span>
        <span>SL: <strong className="text-rose-400">{formatUsd(h.sl_price)}</strong></span>
      </div>

      {/* Line 3: Signal Strength / Filter Badge (e.g. 🎯 ELITE EXECUTE SHORT or ⛔ FILTER (MACRO CONFLICT)) */}
      <div className="mt-0.5">
        <span
          className={`inline-block rounded px-1.5 py-0.5 text-[9.5px] font-bold font-sans border tracking-tight leading-snug whitespace-normal ${badgeStyle}`}
        >
          {decision}
        </span>
      </div>
    </div>
  );
}

export default function AssetPredictionMatrix() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: status } = useStatusQuery();
  const { isStarred, toggleWatchlist, watchlist } = useWatchlist();
  const [selectedHorizon, setSelectedHorizon] = useState<HorizonKey>("all");
  const [search, setSearch] = useState("");
  const [selectedCoin, setSelectedCoin] = useState<{ symbol: string; price?: number } | null>(null);

  const leaderboard = useMemo(() => forecast?.scanner_leaderboard || [], [forecast?.scanner_leaderboard]);

  const filteredAssets = useMemo(() => {
    let list = leaderboard;
    if (selectedHorizon === "watchlist") {
      list = list.filter((item: any) => isStarred(item.symbol));
    }
    if (search.trim()) {
      const q = search.toLowerCase().trim();
      list = list.filter((item: any) => item.symbol?.toLowerCase().includes(q));
    }
    // Always pin starred / active trade assets at the top while preserving rank
    return [...list].sort((a: any, b: any) => {
      const aStarred = isStarred(a.symbol);
      const bStarred = isStarred(b.symbol);
      if (aStarred && !bStarred) return -1;
      if (!aStarred && bStarred) return 1;
      return 0;
    });
  }, [leaderboard, search, selectedHorizon, isStarred]);

  const horizonTabs: { key: HorizonKey; label: string }[] = useMemo(
    () => [
      { key: "all", label: "All Horizons" },
      { key: "watchlist", label: `⭐ Watchlist (${watchlist.length})` },
      { key: "scalp", label: "⚡ Scalp (15M)" },
      { key: "swing", label: "🌊 Swing (1H)" },
      { key: "macro", label: "🚀 Macro (24H)" },
      { key: "horizon_2d", label: "🔮 2-Day (48H)" },
      { key: "horizon_3d", label: "🔭 3-Day (72H)" },
      { key: "weekly", label: "🗓️ Weekly (7D)" },
      { key: "biweekly", label: "🌕 Bi-Weekly (15D)" },
      { key: "monthly", label: "🪐 Monthly (30D)" },
    ],
    [watchlist.length]
  );

  const handleCloseModal = useCallback(() => setSelectedCoin(null), []);

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      {/* Modal for 15-Minute Historical Signal Audit */}
      {selectedCoin && (
        <CoinSignalHistoryModal
          symbol={selectedCoin.symbol}
          currentPrice={selectedCoin.price}
          onClose={handleCloseModal}
        />
      )}

      {/* Clean Matrix Header */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
              <Zap className="h-5 w-5 text-cyan-400" />
              Complete Top 100-Asset Market Prediction Matrix
            </h2>
            <span className="rounded-md bg-dark-900 px-2.5 py-0.5 text-xs font-semibold text-cyan-300 border border-cyan-700/50">
              {leaderboard.length || 100} Assets Scanned
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Multi-horizon AI predictions, entry prices, 1:2 R:R targets, and confluence grading across Top 100 crypto assets.{" "}
            <span className="text-cyan-400 font-semibold underline decoration-dotted">
              Click any coin row to view its 15-minute historical audit records.
            </span>
          </p>
        </div>
      </div>

      {/* Controls & Horizon Tabs */}
      <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        {/* Horizon Filter Tabs (8 Horizons Spectrum) */}
        <div className="flex items-center gap-1 rounded-xl bg-dark-900/90 p-1 border border-slate-800 overflow-x-auto max-w-full">
          {horizonTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setSelectedHorizon(tab.key)}
              className={`whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-all ${
                selectedHorizon === tab.key
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search Bar */}
        <div className="relative w-full sm:w-64 shrink-0">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search from 100 assets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-xl bg-dark-900/90 pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 border border-slate-800 focus:border-cyan-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Top 100 Assets Full Prediction Table */}
      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800/80">
        <table className="w-full text-left text-xs text-slate-300 font-mono">
          <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="py-3 px-4"># / Asset &amp; Live Price</th>
              {selectedHorizon === "all" ? (
                <>
                  <th className="py-3 px-4">⚡ Scalp (15M)</th>
                  <th className="py-3 px-4">🌊 Swing (1H)</th>
                  <th className="py-3 px-4">🚀 Macro (24H)</th>
                  <th className="py-3 px-4">🗓️ Weekly (7D)</th>
                  <th className="py-3 px-4">🪐 Monthly (30D)</th>
                  <th className="py-3 px-4 text-right">Alignment &amp; History</th>
                </>
              ) : (
                <>
                  <th className="py-3 px-4">Predicted Direction</th>
                  <th className="py-3 px-4">Conviction %</th>
                  <th className="py-3 px-4">Take-Profit Target</th>
                  <th className="py-3 px-4">Invalidation SL</th>
                  <th className="py-3 px-4">Expected Return</th>
                  <th className="py-3 px-4 text-right">Signal Strength / Decision</th>
                </>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
            {isLoading ? (
              <tr>
                <td colSpan={selectedHorizon === "all" ? 7 : 6} className="py-12 text-center text-slate-500 font-sans">
                  Loading Top 100 asset predictions from latest scan...
                </td>
              </tr>
            ) : filteredAssets.length === 0 ? (
              <tr>
                <td colSpan={selectedHorizon === "all" ? 7 : 6} className="py-12 text-center text-slate-500 font-sans">
                  No assets match your search.
                </td>
              </tr>
            ) : (
              filteredAssets.map((item: any, idx: number) => {
                const s = item.horizons?.scalp || {};
                const w = item.horizons?.swing || {};
                const m = item.horizons?.macro || {};
                const h7d = item.horizons?.weekly || {};
                const h30d = item.horizons?.monthly || {};
                const isTriple = item.is_triple_confluence;

                // Specific Horizon View (e.g. 15M, 1H, 24H, 2D, 3D, 7D, 15D, 30D)
                if (selectedHorizon !== "all") {
                  const h = item.horizons?.[selectedHorizon] || {};
                  const isLong = h.direction === "BULLISH" || h.direction === "LONG";
                  const conv = h.conviction ?? 50.0;
                  const expRet = h.exp_return ? h.exp_return * 100 : 0.0;

                  return (
                    <tr
                      key={item.symbol}
                      onClick={() => setSelectedCoin({ symbol: item.symbol, price: item.current_price })}
                      className="hover:bg-slate-800/60 cursor-pointer transition-colors group"
                      title="Click to view 15-minute historical signal records for this coin"
                    >
                      {/* Asset & Price */}
                      <td className="py-3 px-4">
                        <div className="flex items-start gap-2 min-w-[150px]">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleWatchlist(item.symbol);
                            }}
                            className="p-1 mt-0.5 text-slate-500 hover:text-amber-400 transition-colors shrink-0"
                            title={isStarred(item.symbol) ? "Remove from Watchlist" : "Add to Watchlist"}
                          >
                            <Star
                              className={`h-3.5 w-3.5 ${
                                isStarred(item.symbol) ? "fill-amber-400 text-amber-400" : ""
                              }`}
                            />
                          </button>
                          <div className="flex flex-col gap-1">
                            {/* Asset Status Badge */}
                            <div className="flex items-center gap-1.5">
                              {isTriple ? (
                                <span
                                  className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-black border tracking-tight shadow-sm ${
                                    s.direction === "BULLISH"
                                      ? "bg-emerald-950/90 text-emerald-300 border-emerald-500/70 shadow-emerald-500/20"
                                      : "bg-rose-950/90 text-rose-300 border-rose-500/70 shadow-rose-500/20"
                                  }`}
                                >
                                  {s.direction === "BULLISH" ? "💎 TRIPLE BUY" : "💎 TRIPLE SELL"}
                                </span>
                              ) : idx === 0 ? (
                                <span className="inline-flex items-center gap-1 rounded bg-amber-950/80 px-1.5 py-0.5 text-[10px] font-bold text-amber-300 border border-amber-500/50">
                                  🥇 TOP PICK
                                </span>
                              ) : (
                                <span className="text-slate-500 font-sans text-xs font-semibold">#{idx + 1}</span>
                              )}
                            </div>

                            {/* Symbol & Price */}
                            <div className="flex items-baseline gap-1.5">
                              <span className="font-bold text-white text-sm font-sans group-hover:text-cyan-400 transition-colors flex items-center gap-1">
                                {item.symbol}
                                <History className="h-3 w-3 text-cyan-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                              </span>
                              <span className="text-xs font-mono font-semibold text-cyan-400">
                                ({formatUsd(item.current_price)})
                              </span>
                            </div>
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

                      {/* Signal Strength / Decision */}
                      <td className="py-3 px-4 text-right font-sans">
                        <div className="flex justify-end">
                          {renderSignalCell(h)}
                        </div>
                      </td>
                    </tr>
                  );
                }

                // All-Horizon Combined Overview Row
                return (
                  <tr
                    key={item.symbol}
                    onClick={() => setSelectedCoin({ symbol: item.symbol, price: item.current_price })}
                    className="hover:bg-slate-800/60 cursor-pointer transition-colors group"
                    title="Click to view 15-minute historical signal records for this coin"
                  >
                    {/* Asset & Price */}
                    <td className="py-3 px-4">
                      <div className="flex items-start gap-2 min-w-[150px]">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleWatchlist(item.symbol);
                          }}
                          className="p-1 mt-0.5 text-slate-500 hover:text-amber-400 transition-colors shrink-0"
                          title={isStarred(item.symbol) ? "Remove from Watchlist" : "Add to Watchlist"}
                        >
                          <Star
                            className={`h-3.5 w-3.5 ${
                              isStarred(item.symbol) ? "fill-amber-400 text-amber-400" : ""
                            }`}
                          />
                        </button>
                        <div className="flex flex-col gap-1">
                          {/* Asset Status Badge */}
                          <div className="flex items-center gap-1.5">
                            {isTriple ? (
                              <span
                                className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-black border tracking-tight shadow-sm ${
                                  s.direction === "BULLISH"
                                    ? "bg-emerald-950/90 text-emerald-300 border-emerald-500/70 shadow-emerald-500/20"
                                    : "bg-rose-950/90 text-rose-300 border-rose-500/70 shadow-rose-500/20"
                                }`}
                              >
                                {s.direction === "BULLISH" ? "💎 TRIPLE BUY" : "💎 TRIPLE SELL"}
                              </span>
                            ) : idx === 0 ? (
                              <span className="inline-flex items-center gap-1 rounded bg-amber-950/80 px-1.5 py-0.5 text-[10px] font-bold text-amber-300 border border-amber-500/50">
                                🥇 TOP PICK
                              </span>
                            ) : (
                              <span className="text-slate-500 font-sans text-xs font-semibold">#{idx + 1}</span>
                            )}
                          </div>

                          {/* Symbol & Price */}
                          <div className="flex items-baseline gap-1.5">
                            <span className="font-bold text-white text-sm font-sans group-hover:text-cyan-400 transition-colors flex items-center gap-1">
                              {item.symbol}
                              <History className="h-3 w-3 text-cyan-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                            </span>
                            <span className="text-xs font-mono font-semibold text-cyan-400">
                              ({formatUsd(item.current_price)})
                            </span>
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Scalp (15M) */}
                    <td className="py-3 px-4">
                      {renderSignalCell(s)}
                    </td>

                    {/* Swing (1H) */}
                    <td className="py-3 px-4">
                      {renderSignalCell(w)}
                    </td>

                    {/* Macro (24H) */}
                    <td className="py-3 px-4">
                      {renderSignalCell(m)}
                    </td>

                    {/* Weekly (7D) */}
                    <td className="py-3 px-4">
                      {renderSignalCell(h7d)}
                    </td>

                    {/* Monthly (30D) */}
                    <td className="py-3 px-4">
                      {renderSignalCell(h30d)}
                    </td>

                    {/* Alignment & Drilldown Action */}
                    <td className="py-3 px-4 text-right font-sans">
                      <div className="flex items-center justify-end gap-2">
                        {isTriple ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-cyan-950 px-2 py-0.5 text-[10px] font-black text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20">
                            <Sparkles className="h-3 w-3" /> TRIPLE
                          </span>
                        ) : null}
                        <span className="inline-flex items-center gap-1 rounded-lg bg-dark-900 hover:bg-cyan-950 px-2 py-1 text-[10px] font-semibold text-cyan-400 border border-slate-800 hover:border-cyan-500 transition-colors">
                          <History className="h-3 w-3" /> 15M History
                        </span>
                      </div>
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
