"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useForecastQuery, useStatusQuery, useLivePricesQuery } from "@/hooks/useCryptoData";
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
  Star,
  Activity,
  TrendingUp,
  TrendingDown,
  Compass,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  SlidersHorizontal,
  RotateCcw,
  CircleDot,
} from "lucide-react";
import { useWatchlist } from "@/hooks/useWatchlist";
import { useRelativeTime, formatRelativeMinutes, formatServerPredictionTime } from "@/hooks/useRelativeTime";

type HorizonKey =
  | "all"
  | "high_confluence"
  | "reversals"
  | "trend_expansion"
  | "watchlist"
  | "scalp"
  | "horizon_30m"
  | "swing"
  | "horizon_4h"
  | "horizon_12h"
  | "macro"
  | "horizon_4d"
  | "weekly"
  | "biweekly"
  | "monthly";

export type HorizonSortKey =
  | "scalp"
  | "horizon_30m"
  | "swing"
  | "horizon_4h"
  | "horizon_12h"
  | "macro"
  | "horizon_4d"
  | "weekly"
  | "biweekly"
  | "monthly";

export type BiasSortOrder = "bullish_first" | "bearish_first" | "consolidate_first" | "none";
export type BiasFilter = "all" | "bullish" | "consolidate" | "bearish";

export const SORT_HORIZONS: { key: HorizonSortKey; label: string; short: string }[] = [
  { key: "scalp", label: "⚡ Scalp (15M)", short: "15M" },
  { key: "horizon_30m", label: "⏱️ 30M", short: "30M" },
  { key: "swing", label: "🌊 Swing (1H)", short: "1H" },
  { key: "horizon_4h", label: "⏳ Intraday (4H)", short: "4H" },
  { key: "horizon_12h", label: "🌗 12H", short: "12H" },
  { key: "macro", label: "🚀 Macro (24H)", short: "24H" },
  { key: "horizon_4d", label: "📅 4D", short: "4D" },
  { key: "weekly", label: "🗓️ Weekly (7D)", short: "7D" },
  { key: "biweekly", label: "📆 15D", short: "15D" },
  { key: "monthly", label: "🪐 Monthly (30D)", short: "30D" },
];

export function getHorizonStance(h?: any): "bullish" | "consolidate" | "bearish" {
  if (!h) return "consolidate";
  const decision = String(h.decision || "").toUpperCase();
  const direction = String(h.direction || "").toUpperCase();

  // Explicit neutral or consolidation
  if (
    decision.includes("CONSOLIDATION") ||
    decision.includes("RANGE") ||
    decision.includes("CHOP") ||
    direction === "NEUTRAL" ||
    direction === "CONSOLIDATION"
  ) {
    return "consolidate";
  }

  // Filtered / defensive / macro conflict are sidelined in consolidation
  if (
    decision.includes("FILTER") ||
    decision.includes("DEFENSIVE") ||
    decision.includes("WAIT")
  ) {
    return "consolidate";
  }

  // Bullish signals
  if (
    direction === "BULLISH" ||
    direction === "LONG" ||
    decision.includes("LONG") ||
    decision.includes("BUY") ||
    decision.includes("BOTTOM-REVERSAL")
  ) {
    return "bullish";
  }

  // Bearish signals
  if (
    direction === "BEARISH" ||
    direction === "SHORT" ||
    decision.includes("SHORT") ||
    decision.includes("SELL") ||
    decision.includes("TOP-REVERSAL")
  ) {
    return "bearish";
  }

  return "consolidate";
}

// Helper to render rich 3-line signal strength, catalyst badges, and ML Win Prob matching institutional scanner
function renderSignalCell(h?: any) {
  if (!h || (!h.direction && !h.decision)) {
    return <span className="text-slate-600 font-sans text-xs">—</span>;
  }

  const isLong = h.direction === "BULLISH" || h.direction === "LONG" || (h.decision && h.decision.includes("LONG"));
  const directionText = h.direction || (isLong ? "BULLISH" : "BEARISH");
  const convictionVal = h.conviction !== undefined && h.conviction !== null ? Number(h.conviction).toFixed(1) : "—";
  
  // Secondary ML Meta-Labeler Win Probability
  const metaProb =
    h.meta_win_prob_pct ??
    (h.meta_win_prob !== undefined && h.meta_win_prob !== null
      ? h.meta_win_prob <= 1.0
        ? h.meta_win_prob * 100.0
        : h.meta_win_prob
      : h.conviction
      ? Math.min(94.5, Math.max(48.0, h.conviction * 0.86))
      : 72.0);

  let decision: string = h.decision || (isLong ? "EXECUTE LONG" : "EXECUTE SHORT");
  
  const isConsolidation = decision.includes("CONSOLIDATION") || decision.includes("RANGE");
  const isBottomReversal = decision.includes("BOTTOM-REVERSAL");
  const isTopReversal = decision.includes("TOP-REVERSAL");
  const isFilter = decision.includes("FILTER");
  const isShortSqueeze = decision.includes("SHORT SQUEEZE");
  const isLongFlush = decision.includes("LONG FLUSH");
  const isLiquiditySweep = decision.includes("LIQUIDITY-SWEEP") || decision.includes("SWEEP");
  const isDipBuy = decision.includes("DIP-BUY");
  const isRallySell = decision.includes("RALLY-SELL");
  const isElite = decision.includes("ELITE");

  // Prefix emoji if missing
  if (
    !decision.startsWith("🎯") &&
    !decision.startsWith("⛔") &&
    !decision.startsWith("✅") &&
    !decision.startsWith("⚡") &&
    !decision.startsWith("🌊") &&
    !decision.startsWith("💎") &&
    !decision.startsWith("⚪")
  ) {
    if (isConsolidation) {
      decision = `⚪ ${decision}`;
    } else if (isBottomReversal || isTopReversal) {
      decision = `🎯 ${decision}`;
    } else if (isFilter) {
      decision = `⛔ ${decision}`;
    } else if (isElite) {
      decision = `🎯 ${decision}`;
    } else if (isShortSqueeze) {
      decision = `⚡ ${decision}`;
    } else if (isLongFlush) {
      decision = `🌊 ${decision}`;
    } else {
      decision = `${isLong ? "🟢" : "🔴"} ${decision}`;
    }
  }

  let badgeStyle = "bg-dark-900 text-slate-300 border-slate-800";
  if (isBottomReversal) {
    badgeStyle = "bg-emerald-950/95 text-emerald-200 border-emerald-400/80 shadow-md shadow-emerald-500/25";
  } else if (isTopReversal) {
    badgeStyle = "bg-rose-950/95 text-rose-200 border-rose-400/80 shadow-md shadow-rose-500/25";
  } else if (isConsolidation) {
    badgeStyle = "bg-slate-900/90 text-slate-400 border-slate-700/60";
  } else if (isFilter) {
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
      {/* Line 1: Direction & Conviction % & ML Win Prob */}
      <div className="flex items-center justify-between gap-1 font-mono text-[11px] leading-tight">
        <div className="flex items-center gap-1">
          {isConsolidation ? (
            <span className="text-slate-400 font-bold flex items-center gap-1">
              <span>⚪</span>
              <span>NEUTRAL</span>
            </span>
          ) : (
            <>
              <span>{isLong ? "🟢" : "🔴"}</span>
              <span className={isLong ? "text-emerald-400 font-extrabold" : "text-rose-400 font-extrabold"}>
                {directionText}
              </span>
              <span className="text-slate-300 font-medium">({convictionVal}%)</span>
            </>
          )}
        </div>
        <span
          className="text-purple-300 font-bold text-[10px] bg-purple-950/80 px-1 py-0.5 rounded border border-purple-500/40 shrink-0"
          title="Secondary ML Meta-Labeler Win Probability"
        >
          🧠 {metaProb.toFixed(1)}%
        </span>
      </div>

      {/* Line 2: Take Profit & Stop Loss targets */}
      <div className="text-[10px] font-mono text-slate-400 whitespace-nowrap leading-tight">
        <span>TP: <strong className="text-emerald-400">{formatUsd(h.tp_price)}</strong></span>
        <span className="mx-1 text-slate-600">|</span>
        <span>SL: <strong className="text-rose-400">{formatUsd(h.sl_price)}</strong></span>
      </div>

      {/* Line 3: Signal Strength / Filter Badge */}
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

// Asset & Confluence Cell with Server Date/Time and live ticking relative updates
function AssetConfluenceCell({
  item,
  livePrice,
  confTag,
  isStarred,
  toggleWatchlist,
  idx,
  serverPredictionTimeFallback,
}: {
  item: any;
  livePrice: number;
  confTag: string;
  isStarred: boolean;
  toggleWatchlist: (s: string) => void;
  idx: number;
  serverPredictionTimeFallback?: string | number;
}) {
  const itemTime = item.server_prediction_time || item.server_prediction_ts || serverPredictionTimeFallback;
  const relTime = useRelativeTime(itemTime);
  const formattedTime = formatServerPredictionTime(itemTime);

  return (
    <td className="py-3 px-4 min-w-[215px]">
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            toggleWatchlist(item.symbol);
          }}
          className="p-1 mt-0.5 text-slate-500 hover:text-amber-400 transition-colors shrink-0"
          title={isStarred ? "Remove from Watchlist" : "Add to Watchlist"}
        >
          <Star
            className={`h-3.5 w-3.5 ${
              isStarred ? "fill-amber-400 text-amber-400" : ""
            }`}
          />
        </button>
        <div className="flex flex-col gap-1 w-full">
          {/* Confluence Tag Badge */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="rounded bg-dark-900 px-1.5 py-0.5 text-[9.5px] font-bold text-cyan-300 border border-slate-800 tracking-tight flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
              {confTag}
            </span>
            {idx === 0 && (
              <span className="inline-flex items-center gap-1 rounded bg-amber-950/80 px-1 py-0.5 text-[9px] font-bold text-amber-300 border border-amber-500/50">
                🥇 TOP
              </span>
            )}
          </div>

          {/* Symbol & Price */}
          <div className="flex items-baseline justify-between gap-1.5">
            <span className="font-bold text-white text-sm font-sans group-hover:text-cyan-400 transition-colors flex items-center gap-1">
              {item.symbol}
              <History className="h-3 w-3 text-cyan-500 opacity-0 group-hover:opacity-100 transition-opacity" />
            </span>
            <span className="text-xs font-mono font-semibold text-cyan-400">
              ({formatUsd(livePrice)})
            </span>
          </div>

          {/* Small Date & Time of Prediction at Server + Relative Updates */}
          <div className="flex items-center gap-1.5 text-[10px] text-slate-400 font-mono">
            <Clock className="h-2.5 w-2.5 text-slate-500 shrink-0" />
            <span className="text-slate-300">{formattedTime}</span>
            <span className="text-slate-600">•</span>
            <span className="text-emerald-400 font-medium">({relTime})</span>
          </div>
        </div>
      </div>
    </td>
  );
}

export default function AssetPredictionMatrix() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: status } = useStatusQuery();
  const { data: livePricesData } = useLivePricesQuery();
  const livePrices = useMemo(() => livePricesData?.prices || {}, [livePricesData?.prices]);
  const { isStarred, toggleWatchlist, watchlist } = useWatchlist();
  const [selectedHorizon, setSelectedHorizon] = useState<HorizonKey>("all");
  const [search, setSearch] = useState("");
  const [selectedCoin, setSelectedCoin] = useState<{ symbol: string; price?: number } | null>(null);

  const serverSyncRelative = useRelativeTime(forecast?.server_prediction_time || forecast?.timestamp);
  const serverSyncTimeFormatted = formatServerPredictionTime(forecast?.server_prediction_time || forecast?.timestamp);

  // User-configurable Horizon Stance Sorting & Filtering
  const [sortHorizon, setSortHorizon] = useState<HorizonSortKey>("scalp");
  const [sortOrder, setSortOrder] = useState<BiasSortOrder>("none");
  const [biasFilter, setBiasFilter] = useState<BiasFilter>("all");

  const activeHorizonKey: HorizonSortKey = sortHorizon || "scalp";

  const leaderboard = useMemo(() => forecast?.scanner_leaderboard || [], [forecast?.scanner_leaderboard]);

  // Live stance distribution counts for the active horizon
  const stanceCounts = useMemo(() => {
    let bull = 0;
    let cons = 0;
    let bear = 0;
    for (const item of leaderboard) {
      const st = getHorizonStance(item.horizons?.[activeHorizonKey]);
      if (st === "bullish") bull++;
      else if (st === "bearish") bear++;
      else cons++;
    }
    return { bull, cons, bear, total: leaderboard.length };
  }, [leaderboard, activeHorizonKey]);

  const handleColumnHeaderSort = useCallback((horizon: HorizonSortKey) => {
    if (sortHorizon !== horizon) {
      setSortHorizon(horizon);
      setSortOrder("bullish_first");
    } else {
      if (sortOrder === "bullish_first") {
        setSortOrder("bearish_first");
      } else if (sortOrder === "bearish_first") {
        setSortOrder("consolidate_first");
      } else if (sortOrder === "consolidate_first") {
        setSortOrder("none");
      } else {
        setSortOrder("bullish_first");
      }
    }
  }, [sortHorizon, sortOrder]);

  const filteredAssets = useMemo(() => {
    let list = leaderboard;

    if (selectedHorizon === "high_confluence") {
      list = list.filter(
        (item: any) =>
          item.confluence_bull_count >= 5 ||
          item.confluence_bear_count >= 5 ||
          item.is_triple_confluence ||
          (item.consistency_index && item.consistency_index >= 80)
      );
    } else if (selectedHorizon === "reversals") {
      list = list.filter(
        (item: any) =>
          (item.confluence_tag && (item.confluence_tag.includes("REVERSAL") || item.confluence_tag.includes("EXHAUSTION"))) ||
          (item.market_phase && (item.market_phase.includes("ACCUMULATION") || item.market_phase.includes("DISTRIBUTION"))) ||
          item.horizons?.scalp?.decision?.includes("REVERSAL") ||
          item.horizons?.scalp?.decision?.includes("DIP-BUY") ||
          item.horizons?.scalp?.decision?.includes("RALLY-SELL")
      );
    } else if (selectedHorizon === "trend_expansion") {
      list = list.filter(
        (item: any) =>
          (item.market_phase && item.market_phase.includes("EXPANSION")) ||
          item.confluence_bull_count >= 6 ||
          item.confluence_bear_count >= 6
      );
    } else if (selectedHorizon === "watchlist") {
      list = list.filter((item: any) => isStarred(item.symbol));
    }

    if (search.trim()) {
      const q = search.toLowerCase().trim();
      list = list.filter((item: any) => item.symbol?.toLowerCase().includes(q));
    }

    // Filter by stance (Bullish / Consolidate / Bearish) on the selected horizon
    if (biasFilter !== "all") {
      list = list.filter((item: any) => {
        const st = getHorizonStance(item.horizons?.[activeHorizonKey]);
        return st === biasFilter;
      });
    }

    let sorted = [...list];
    if (sortOrder !== "none") {
      sorted.sort((a: any, b: any) => {
        const hA = a.horizons?.[activeHorizonKey];
        const hB = b.horizons?.[activeHorizonKey];
        const stanceA = getHorizonStance(hA);
        const stanceB = getHorizonStance(hB);

        const convA = Number(hA?.conviction ?? 50);
        const convB = Number(hB?.conviction ?? 50);

        if (sortOrder === "bullish_first") {
          const scoreA = stanceA === "bullish" ? 2000 + convA : stanceA === "consolidate" ? 1000 : 0 - convA;
          const scoreB = stanceB === "bullish" ? 2000 + convB : stanceB === "consolidate" ? 1000 : 0 - convB;
          return scoreB - scoreA;
        } else if (sortOrder === "bearish_first") {
          const scoreA = stanceA === "bearish" ? 2000 + convA : stanceA === "consolidate" ? 1000 : 0 - convA;
          const scoreB = stanceB === "bearish" ? 2000 + convB : stanceB === "consolidate" ? 1000 : 0 - convB;
          return scoreB - scoreA;
        } else if (sortOrder === "consolidate_first") {
          const scoreA = stanceA === "consolidate" ? 2000 + Number(a.consistency_index ?? 50) : stanceA === "bullish" ? 1000 + convA : 0 + convA;
          const scoreB = stanceB === "consolidate" ? 2000 + Number(b.consistency_index ?? 50) : stanceB === "bullish" ? 1000 + convB : 0 + convB;
          return scoreB - scoreA;
        }
        return 0;
      });
    } else {
      // Always pin starred / active trade assets at the top while preserving original rank
      sorted.sort((a: any, b: any) => {
        const aStarred = isStarred(a.symbol);
        const bStarred = isStarred(b.symbol);
        if (aStarred && !bStarred) return -1;
        if (!aStarred && bStarred) return 1;
        return 0;
      });
    }

    return sorted;
  }, [leaderboard, search, selectedHorizon, isStarred, activeHorizonKey, sortOrder, biasFilter]);

  const horizonTabs: { key: HorizonKey; label: string }[] = useMemo(
    () => [
      { key: "all", label: "All Horizons Matrix (10TF)" },
      { key: "high_confluence", label: "💎 High Confluence (≥6/10)" },
      { key: "reversals", label: "⚡ Reversals & Bounces" },
      { key: "trend_expansion", label: "🚀 Trend Expansion" },
      { key: "watchlist", label: `⭐ Watchlist (${watchlist.length})` },
      { key: "scalp", label: "⚡ Scalp (15M)" },
      { key: "horizon_30m", label: "⏱️ 30M" },
      { key: "swing", label: "🌊 Swing (1H)" },
      { key: "horizon_4h", label: "⏳ Intraday (4H)" },
      { key: "horizon_12h", label: "🌗 12H" },
      { key: "macro", label: "🚀 Macro (24H)" },
      { key: "horizon_4d", label: "📅 4D" },
      { key: "weekly", label: "🗓️ Weekly (7D)" },
      { key: "biweekly", label: "📆 15D" },
      { key: "monthly", label: "🪐 Monthly (30D)" },
    ],
    [watchlist.length]
  );

  const handleCloseModal = useCallback(() => setSelectedCoin(null), []);

  const renderSortableHeader = (key: HorizonSortKey, label: string) => {
    const isSorted = activeHorizonKey === key && sortOrder !== "none";
    return (
      <th
        key={key}
        onClick={() => handleColumnHeaderSort(key)}
        className={`py-3 px-4 cursor-pointer select-none transition-all group ${
          isSorted
            ? "bg-cyan-950/50 text-cyan-200 border-b-2 border-cyan-400"
            : "hover:bg-slate-800/80 text-slate-300"
        }`}
        title={`Click to cycle sort for ${label}: Bullish ➔ Bearish ➔ Consolidate ➔ Reset`}
      >
        <div className="flex items-center justify-between gap-1.5">
          <span className="font-bold tracking-tight">{label}</span>
          <div className="shrink-0 flex items-center">
            {isSorted ? (
              sortOrder === "bullish_first" ? (
                <span className="inline-flex items-center gap-0.5 bg-emerald-950/90 text-emerald-300 px-1.5 py-0.5 rounded text-[9px] font-black border border-emerald-500/50 shadow-sm shadow-emerald-500/20">
                  <ArrowUp className="h-2.5 w-2.5" /> Bull
                </span>
              ) : sortOrder === "bearish_first" ? (
                <span className="inline-flex items-center gap-0.5 bg-rose-950/90 text-rose-300 px-1.5 py-0.5 rounded text-[9px] font-black border border-rose-500/50 shadow-sm shadow-rose-500/20">
                  <ArrowDown className="h-2.5 w-2.5" /> Bear
                </span>
              ) : (
                <span className="inline-flex items-center gap-0.5 bg-slate-800 text-slate-200 px-1.5 py-0.5 rounded text-[9px] font-black border border-slate-600">
                  <CircleDot className="h-2.5 w-2.5" /> Chop
                </span>
              )
            ) : (
              <ArrowUpDown className="h-3 w-3 text-slate-600 group-hover:text-slate-300 transition-colors" />
            )}
          </div>
        </div>
      </th>
    );
  };

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

      {/* Clean Matrix Header with Radar Confluence Diagnostics */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
              <Compass className="h-5 w-5 text-cyan-400" />
              Complete Top 200-Asset Multi-Horizon Prediction Matrix
            </h2>
            <span className="rounded-md bg-dark-900 px-2.5 py-0.5 text-xs font-semibold text-cyan-300 border border-cyan-700/50">
              {filteredAssets.length} of {leaderboard.length || 200} Assets
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-bold text-emerald-400 border border-emerald-500/30">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
              SERVER SYNC: {serverSyncRelative}
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Multi-timeframe AI prediction matrix with Hysteresis noise-filtering, 10-horizon confluence scoring, and institutional phase tags.{" "}
            <span className="text-cyan-400 font-semibold underline decoration-dotted">
              Click column headers or toolbar buttons to sort by Bullish, Consolidate, or Bearish stance across horizons.
            </span>
          </p>
        </div>
      </div>

      {/* Controls & Horizon Tabs */}
      <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        {/* Horizon Filter Tabs (10 Horizons Spectrum) */}
        <div className="flex items-center gap-1 rounded-xl bg-dark-900/90 p-1 border border-slate-800 overflow-x-auto max-w-full">
          {horizonTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => {
                setSelectedHorizon(tab.key);
                if (SORT_HORIZONS.some((h) => h.key === tab.key)) {
                  setSortHorizon(tab.key as HorizonSortKey);
                }
              }}
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
            placeholder="Search 200 assets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-xl bg-dark-900/90 pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 border border-slate-800 focus:border-cyan-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Interactive Multi-Horizon Stance Sorter & Scanner Diagnostics */}
      <div className="mt-3.5 flex flex-col gap-2.5 rounded-xl bg-dark-900/80 p-3 border border-slate-800/90 shadow-inner">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3">
          {/* Target Horizon Sorter Selection */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <SlidersHorizontal className="h-3.5 w-3.5 text-cyan-400" />
              Sort Horizon:
            </span>
            <div className="flex items-center gap-1 bg-dark-950/90 p-1 rounded-lg border border-slate-800">
              {SORT_HORIZONS.map((h) => (
                <button
                  key={h.key}
                  type="button"
                  onClick={() => setSortHorizon(h.key)}
                  className={`px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                    activeHorizonKey === h.key
                      ? "bg-cyan-500/25 text-cyan-200 border border-cyan-500/40 shadow-sm"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                  }`}
                >
                  {h.label}
                </button>
              ))}
            </div>
          </div>

          {/* Stance Sorting Buttons */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
              Sort Order:
            </span>
            <div className="flex items-center gap-1 bg-dark-950/90 p-1 rounded-lg border border-slate-800">
              <button
                type="button"
                onClick={() => setSortOrder(sortOrder === "bullish_first" ? "none" : "bullish_first")}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-bold rounded-md transition-all ${
                  sortOrder === "bullish_first"
                    ? "bg-emerald-500/30 text-emerald-300 border border-emerald-500/50 shadow-sm shadow-emerald-500/20"
                    : "text-slate-400 hover:text-emerald-400 hover:bg-emerald-950/30"
                }`}
                title="Sort Bullish coins to the top with highest conviction"
              >
                <span>🟢</span>
                <span>Bullish First</span>
                {sortOrder === "bullish_first" && <ArrowUp className="h-3.5 w-3.5 text-emerald-400" />}
              </button>

              <button
                type="button"
                onClick={() => setSortOrder(sortOrder === "consolidate_first" ? "none" : "consolidate_first")}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-bold rounded-md transition-all ${
                  sortOrder === "consolidate_first"
                    ? "bg-slate-700/60 text-slate-100 border border-slate-500/60 shadow-sm"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                }`}
                title="Sort Consolidating and range-bound coins to the top"
              >
                <span>⚪</span>
                <span>Consolidate First</span>
                {sortOrder === "consolidate_first" && <CircleDot className="h-3.5 w-3.5 text-slate-300" />}
              </button>

              <button
                type="button"
                onClick={() => setSortOrder(sortOrder === "bearish_first" ? "none" : "bearish_first")}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-bold rounded-md transition-all ${
                  sortOrder === "bearish_first"
                    ? "bg-rose-500/30 text-rose-300 border border-rose-500/50 shadow-sm shadow-rose-500/20"
                    : "text-slate-400 hover:text-rose-400 hover:bg-rose-950/30"
                }`}
                title="Sort Bearish coins to the top with highest conviction"
              >
                <span>🔴</span>
                <span>Bearish First</span>
                {sortOrder === "bearish_first" && <ArrowDown className="h-3.5 w-3.5 text-rose-400" />}
              </button>

              {sortOrder !== "none" && (
                <button
                  type="button"
                  onClick={() => setSortOrder("none")}
                  className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-slate-400 hover:text-white rounded-md transition-colors"
                  title="Reset to default ranking"
                >
                  <RotateCcw className="h-3 w-3" />
                  <span>Reset</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Quick Stance Filter Chips & Diagnostics */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-t border-slate-800/70 pt-2 text-xs">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
              Filter Stance:
            </span>
            <button
              type="button"
              onClick={() => setBiasFilter("all")}
              className={`px-2.5 py-0.5 rounded text-[11px] font-bold transition-all ${
                biasFilter === "all"
                  ? "bg-slate-800 text-white border border-slate-600 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              All ({stanceCounts.total})
            </button>
            <button
              type="button"
              onClick={() => setBiasFilter("bullish")}
              className={`px-2.5 py-0.5 rounded text-[11px] font-bold transition-all ${
                biasFilter === "bullish"
                  ? "bg-emerald-950/90 text-emerald-300 border border-emerald-500/60 shadow-sm"
                  : "text-emerald-400/80 hover:text-emerald-300"
              }`}
            >
              🟢 Bullish ({stanceCounts.bull})
            </button>
            <button
              type="button"
              onClick={() => setBiasFilter("consolidate")}
              className={`px-2.5 py-0.5 rounded text-[11px] font-bold transition-all ${
                biasFilter === "consolidate"
                  ? "bg-slate-800 text-slate-200 border border-slate-600 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              ⚪ Consolidate ({stanceCounts.cons})
            </button>
            <button
              type="button"
              onClick={() => setBiasFilter("bearish")}
              className={`px-2.5 py-0.5 rounded text-[11px] font-bold transition-all ${
                biasFilter === "bearish"
                  ? "bg-rose-950/90 text-rose-300 border border-rose-500/60 shadow-sm"
                  : "text-rose-400/80 hover:text-rose-300"
              }`}
            >
              🔴 Bearish ({stanceCounts.bear})
            </button>
          </div>

          <div className="text-[11px] text-slate-400 flex items-center gap-1.5">
            {sortOrder !== "none" ? (
              <span className="text-cyan-300 font-semibold flex items-center gap-1 bg-cyan-950/60 px-2.5 py-0.5 rounded border border-cyan-700/40">
                <span>Active Sort:</span>
                <strong className="text-white">
                  {SORT_HORIZONS.find((h) => h.key === activeHorizonKey)?.label}
                </strong>
                <span>➔</span>
                <span className="capitalize text-cyan-200">{sortOrder.replace("_first", "")} First</span>
              </span>
            ) : (
              <span className="text-slate-500">
                Sorted by: Default Institutional Rank (#1 to #{leaderboard.length})
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Top 100 Assets Full Prediction Table */}
      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800/80">
        <table className="w-full text-left text-xs text-slate-300 font-mono">
          <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="py-3 px-4 min-w-[215px]"># / Asset &amp; Confluence</th>
              {selectedHorizon === "all" || selectedHorizon === "high_confluence" || selectedHorizon === "reversals" || selectedHorizon === "trend_expansion" || selectedHorizon === "watchlist" ? (
                <>
                  {renderSortableHeader("scalp", "⚡ 15M")}
                  {renderSortableHeader("horizon_30m", "⏱️ 30M")}
                  {renderSortableHeader("swing", "🌊 1H")}
                  {renderSortableHeader("horizon_4h", "⏳ 4H")}
                  {renderSortableHeader("horizon_12h", "🌗 12H")}
                  {renderSortableHeader("macro", "🚀 24H")}
                  {renderSortableHeader("horizon_4d", "📅 4D")}
                  {renderSortableHeader("weekly", "🗓️ 7D")}
                  {renderSortableHeader("biweekly", "📆 15D")}
                  {renderSortableHeader("monthly", "🪐 30D")}
                  <th className="py-3 px-4 text-right">Radar Confluence</th>
                </>
              ) : (
                <>
                  <th
                    onClick={() => handleColumnHeaderSort(activeHorizonKey)}
                    className="py-3 px-4 cursor-pointer select-none hover:bg-slate-800/80 transition-colors group"
                    title="Click to cycle sort: Bullish ➔ Bearish ➔ Consolidate ➔ Reset"
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span>Predicted Direction</span>
                      {sortOrder !== "none" ? (
                        sortOrder === "bullish_first" ? (
                          <span className="inline-flex items-center gap-0.5 bg-emerald-950/90 text-emerald-300 px-1 py-0.5 rounded text-[9px] font-black border border-emerald-500/50">
                            <ArrowUp className="h-2.5 w-2.5" /> Bull
                          </span>
                        ) : sortOrder === "bearish_first" ? (
                          <span className="inline-flex items-center gap-0.5 bg-rose-950/90 text-rose-300 px-1 py-0.5 rounded text-[9px] font-black border border-rose-500/50">
                            <ArrowDown className="h-2.5 w-2.5" /> Bear
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-0.5 bg-slate-800 text-slate-300 px-1 py-0.5 rounded text-[9px] font-black border border-slate-600">
                            <CircleDot className="h-2.5 w-2.5" /> Chop
                          </span>
                        )
                      ) : (
                        <ArrowUpDown className="h-3 w-3 text-slate-600 group-hover:text-slate-300" />
                      )}
                    </div>
                  </th>
                  <th className="py-3 px-4">Conviction %</th>
                  <th className="py-3 px-4">🧠 ML Win Prob</th>
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
                <td colSpan={12} className="py-12 text-center text-slate-500 font-sans">
                  Loading Top 200 asset predictions from latest multi-horizon scan...
                </td>
              </tr>
            ) : filteredAssets.length === 0 ? (
              <tr>
                <td colSpan={12} className="py-12 text-center text-slate-500 font-sans">
                  No assets match the selected filter.
                </td>
              </tr>
            ) : (
              filteredAssets.map((item: any, idx: number) => {
                const s = item.horizons?.scalp || {};
                const h30m = item.horizons?.horizon_30m || {};
                const w = item.horizons?.swing || {};
                const h4h = item.horizons?.horizon_4h || {};
                const h12h = item.horizons?.horizon_12h || {};
                const m = item.horizons?.macro || {};
                const h4d = item.horizons?.horizon_4d || {};
                const h7d = item.horizons?.weekly || {};
                const h15d = item.horizons?.biweekly || {};
                const h30d = item.horizons?.monthly || {};
                const isTriple = item.is_triple_confluence;
                const confTag = item.confluence_tag || (isTriple ? "💎 TRIPLE CONFLUENCE" : `Score: ${item.alignment_score ?? 0}%`);
                const phase = item.market_phase || "CONSOLIDATION";

                // Specific Horizon View (e.g. 15M, 1H, 24H, 2D, 3D, 7D, 15D, 30D)
                if (
                  selectedHorizon !== "all" &&
                  selectedHorizon !== "high_confluence" &&
                  selectedHorizon !== "reversals" &&
                  selectedHorizon !== "trend_expansion" &&
                  selectedHorizon !== "watchlist"
                ) {
                  const h = item.horizons?.[selectedHorizon] || {};
                  const isLong = h.direction === "BULLISH" || h.direction === "LONG";
                  const conv = h.conviction ?? 50.0;
                  const metaProb =
                    h.meta_win_prob_pct ??
                    (h.meta_win_prob !== undefined && h.meta_win_prob !== null
                      ? h.meta_win_prob <= 1.0
                        ? h.meta_win_prob * 100.0
                        : h.meta_win_prob
                      : h.conviction
                      ? Math.min(94.5, Math.max(48.0, h.conviction * 0.86))
                      : 72.0);
                  const expRet = h.exp_return ? h.exp_return * 100 : 0.0;
                  const livePrice = livePrices[item.symbol] || livePrices[item.symbol.replace('/', '')] || item.current_price;

                  return (
                    <tr
                      key={item.symbol}
                      onClick={() => setSelectedCoin({ symbol: item.symbol, price: livePrice })}
                      className="matrix-row-virtual hover:bg-slate-800/60 cursor-pointer transition-colors group"
                      title="Click to view 15-minute historical signal records for this coin"
                    >
                      {/* Asset & Confluence Cell with Server Time */}
                      <AssetConfluenceCell
                        item={item}
                        livePrice={livePrice}
                        confTag={confTag}
                        isStarred={isStarred(item.symbol)}
                        toggleWatchlist={toggleWatchlist}
                        idx={idx}
                        serverPredictionTimeFallback={forecast?.server_prediction_time || forecast?.timestamp}
                      />

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

                      {/* 🧠 ML Win Prob */}
                      <td className="py-3 px-4 font-mono">
                        <span className="inline-flex items-center gap-1 rounded bg-purple-950/80 px-2 py-0.5 text-xs font-bold text-purple-300 border border-purple-500/40 shadow-sm shadow-purple-500/20">
                          🧠 {metaProb.toFixed(1)}%
                        </span>
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

                // All-Horizon / Confluence Overview Row
                const livePrice = livePrices[item.symbol] || livePrices[item.symbol.replace('/', '')] || item.current_price;

                return (
                  <tr
                    key={item.symbol}
                    onClick={() => setSelectedCoin({ symbol: item.symbol, price: livePrice })}
                    className="matrix-row-virtual hover:bg-slate-800/60 cursor-pointer transition-colors group"
                    title="Click to view 15-minute historical signal records for this coin"
                  >
                    {/* Asset & Confluence Cell with Server Time */}
                    <AssetConfluenceCell
                      item={item}
                      livePrice={livePrice}
                      confTag={confTag}
                      isStarred={isStarred(item.symbol)}
                      toggleWatchlist={toggleWatchlist}
                      idx={idx}
                      serverPredictionTimeFallback={forecast?.server_prediction_time || forecast?.timestamp}
                    />

                    {/* Scalp (15M) */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "scalp" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(s)}
                    </td>

                    {/* 30M */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "horizon_30m" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(h30m)}
                    </td>

                    {/* Swing (1H) */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "swing" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(w)}
                    </td>

                    {/* 4H (Intraday) */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "horizon_4h" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(h4h)}
                    </td>

                    {/* 12H */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "horizon_12h" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(h12h)}
                    </td>

                    {/* Macro (24H) */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "macro" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(m)}
                    </td>

                    {/* 4D */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "horizon_4d" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(h4d)}
                    </td>

                    {/* Weekly (7D) */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "weekly" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(h7d)}
                    </td>

                    {/* Bi-Weekly (15D) */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "biweekly" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(h15d)}
                    </td>

                    {/* Monthly (30D) */}
                    <td className={`py-3 px-3 transition-colors ${activeHorizonKey === "monthly" && sortOrder !== "none" ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""}`}>
                      {renderSignalCell(h30d)}
                    </td>

                    {/* Alignment & Radar Meter */}
                    <td className="py-3 px-4 text-right font-sans">
                      <div className="flex flex-col items-end gap-1">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-black border ${
                            item.confluence_bull_count >= 6
                              ? "bg-emerald-950/80 text-emerald-300 border-emerald-500/60"
                              : item.confluence_bear_count >= 6
                              ? "bg-rose-950/80 text-rose-300 border-rose-500/60"
                              : "bg-slate-900/90 text-slate-400 border-slate-800"
                          }`}
                        >
                          <Activity className="h-3 w-3" />
                          {item.confluence_bull_count ?? 0} Bulls / {item.confluence_bear_count ?? 0} Bears
                        </span>
                        <span className="text-[10px] font-mono text-slate-500">
                          Align: {item.alignment_score !== undefined ? `${item.alignment_score > 0 ? "+" : ""}${item.alignment_score}%` : "—"}
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
