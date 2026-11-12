"use client";

import React, { useState, useMemo, useCallback, useRef, useEffect } from "react";
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
  Info,
} from "lucide-react";
import { useWatchlist } from "@/hooks/useWatchlist";
import { useRelativeTime, formatRelativeMinutes, formatServerPredictionTime } from "@/hooks/useRelativeTime";

// ============================================================================
// 9 MULTI-HORIZON TIMEFRAME SPECIFICATIONS (USER DEFINED)
// ============================================================================
export interface HorizonDef {
  key: string;
  altKeys: string[];
  label: string;
  short: string;
  badge: string;
  desc: string;
}

export const ALL_9_HORIZONS: HorizonDef[] = [
  { key: "15m", altKeys: ["15M", "scalp"], label: "15m (15 Minutes)", short: "15M", badge: "⚡ 15M", desc: "Primary Scalp & Signal Execution Horizon" },
  { key: "1h", altKeys: ["1H", "swing"], label: "1h (1 Hour)", short: "1H", badge: "⏳ 1H", desc: "Day Trade / Hourly Momentum Context" },
  { key: "4h", altKeys: ["4H"], label: "4h (4 Hours)", short: "4H", badge: "⏳ 4H", desc: "Intermediate Swing & Macro Anchor" },
];

export type HorizonFilterKey =
  | "all"
  | "5m"
  | "15m"
  | "1h"
  | "4h"
  | "12h"
  | "1d"
  | "1w"
  | "15d"
  | "1M"
  | "order_blocks"
  | "high_confluence"
  | "watchlist";

export type BiasSortOrder = "bullish_first" | "bearish_first" | "consolidate_first" | "none";
export type BiasFilter = "all" | "bullish" | "consolidate" | "bearish";

// Helper to reliably extract prediction data for any of the 9 horizons
export function getTimeframeData(item: any, hDef: HorizonDef): any {
  if (!item) return {};

  // 1. Direct check in all_9_timeframe_predictions
  const all9 = item.all_9_timeframe_predictions;
  if (all9 && typeof all9 === "object") {
    if (all9[hDef.key]) return all9[hDef.key];
    for (const alt of hDef.altKeys) {
      if (all9[alt]) return all9[alt];
    }
  }

  // 2. Direct check in horizons dict
  const horizons = item.horizons;
  if (horizons && typeof horizons === "object") {
    if (horizons[hDef.key]) return horizons[hDef.key];
    for (const alt of hDef.altKeys) {
      if (horizons[alt]) return horizons[alt];
    }
  }

  // 3. Fallbacks for legacy fields
  if (hDef.key === "15m" && item.support_15m) return item.support_15m;
  if (hDef.key === "1d" && item.support_24h) return item.support_24h;

  return {};
}

// Helper to determine stance: bullish vs bearish vs consolidate
export function getHorizonStance(h?: any): "bullish" | "consolidate" | "bearish" {
  if (!h || typeof h !== "object") return "consolidate";

  const trend = String(h.trend_state || "").toUpperCase();
  if (trend === "BULLISH") return "bullish";
  if (trend === "BEARISH") return "bearish";
  if (trend === "CONSOLIDATION") return "consolidate";

  const candle = String(h.candle_color || "").toUpperCase();
  if (candle.includes("GREEN") || candle.includes("BULLISH")) return "bullish";
  if (candle.includes("RED") || candle.includes("BEARISH")) return "bearish";

  const direction = String(h.direction || "").toUpperCase();
  if (direction === "LONG" || direction === "BULLISH") return "bullish";
  if (direction === "SHORT" || direction === "BEARISH") return "bearish";

  const decision = String(h.decision || "").toUpperCase();
  if (decision.includes("LONG") || decision.includes("BUY")) return "bullish";
  if (decision.includes("SHORT") || decision.includes("SELL")) return "bearish";

  return "consolidate";
}

// Valid crypto symbol filter (ignores tokenized stocks, delisted tokens, and meme coins)
const MEME_STEMS = [
  "SHIB", "DOGE", "PEPE", "BONK", "WIF", "FLOKI", "TRUMP", "OLD",
  "INU", "ELON", "MOODENG", "POPCAT", "PENGU", "GOAT", "PNUT",
  "SLERF", "FARTCOIN", "CHILLGUY", "MOG", "TURBO", "NEIRO",
  "BABYDOGE", "BRETT", "BOME", "MEME", "CAT", "MEW", "AI16Z"
];

function isValidCryptoSymbol(symbol: string): boolean {
  if (!symbol) return false;
  const upper = symbol.toUpperCase();
  if (MEME_STEMS.some((stem) => upper.includes(stem))) return false;
  const base = upper.replace("/USDT", "").replace("USDT", "");
  if (["USDSOLD", "ERD", "VEN", "BCC", "BCHABC", "BCHSV", "BTT", "NANO", "USDSB"].includes(base)) return false;
  if (base.endsWith("B") && base !== "BNB" && base !== "ARB") return false;
  return true;
}

// Rich 9-Horizon Cell Renderer
function renderMultiHorizonCell(h?: any, livePrice?: number) {
  if (!h || (!h.direction && !h.trend_state && !h.decision && !h.candle_color)) {
    return (
      <div className="flex flex-col items-center justify-center p-2 text-slate-600 font-mono text-[11px]">
        <span>—</span>
      </div>
    );
  }

  const stance = getHorizonStance(h);
  const isBull = stance === "bullish";
  const isBear = stance === "bearish";
  const isChop = stance === "consolidate";

  const directionText = isBull ? "BULLISH" : isBear ? "BEARISH" : "CHOP";
  const candleColor = h.candle_color || (isBull ? "🟢 GREEN" : isBear ? "🔴 RED" : "🟡 NEUTRAL");
  const votes = h.classifier_votes || (isBull ? `${h.bullish_votes ?? 4}/5 BULL` : isBear ? `${h.bearish_votes ?? 4}/5 BEAR` : "3/5 CHOP");
  const consensusProb = h.consensus_probability !== undefined 
    ? (Number(h.consensus_probability) * 100).toFixed(1) 
    : (h.conviction !== undefined ? Number(h.conviction).toFixed(1) : "55.0");

  const metaWinProb = h.meta_win_prob_pct !== undefined 
    ? Number(h.meta_win_prob_pct).toFixed(1) 
    : (h.meta_win_probability_pct !== undefined ? Number(h.meta_win_probability_pct).toFixed(1) : "75.0");

  const curr = (livePrice && livePrice > 0) ? livePrice : (Number(h.current_price) || 1.0);
  const targetPrice = Number(h.predicted_target_price || h.tp1_price || (isBull ? curr * 1.01 : curr * 0.99));
  const changePct = h.predicted_change_pct !== undefined 
    ? Number(h.predicted_change_pct) 
    : (curr > 0 ? ((targetPrice - curr) / curr) * 100 : 0.0);

  // Model breakdowns for hover inspection
  const clfBreakdown = h.classifier_breakdown || {};
  const regBreakdown = h.regressor_breakdown || {};

  return (
    <div
      className="flex flex-col gap-1 py-1.5 px-2 rounded-lg bg-dark-900/60 border border-slate-800/80 hover:border-slate-700 transition-all min-w-[170px] max-w-[210px]"
      title={`[${h.timeframe || ""}] Consensus: ${votes} | Target: ${formatUsd(targetPrice)} (${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%)\nModels: CatBoost, XGBoost, HistGB, ExtraTrees, RandomForest`}
    >
      {/* Line 1: Next Candle Direction & Consensus Prob */}
      <div className="flex items-center justify-between gap-1 font-mono text-[11px] leading-tight">
        <span className={`inline-flex items-center gap-1 font-extrabold ${isBull ? "text-emerald-400" : isBear ? "text-rose-400" : "text-amber-300"}`}>
          <span>{isBull ? "🟢" : isBear ? "🔴" : "🟡"}</span>
          <span>{directionText}</span>
        </span>
        <span className="text-[10px] text-slate-400 font-medium">
          ({consensusProb}%)
        </span>
        <span
          className="text-purple-300 font-bold text-[9.5px] bg-purple-950/80 px-1 py-0.2 rounded border border-purple-500/40 shrink-0 ml-auto"
          title="Secondary ML Meta-Labeler Win Probability"
        >
          🧠 {metaWinProb}%
        </span>
      </div>

      {/* Line 2: 5 Top Regressors Consensus Target Price */}
      <div className={`text-[10px] font-mono px-1.5 py-0.5 rounded border flex items-center justify-between ${
        isBull 
          ? "text-emerald-200 bg-emerald-950/40 border-emerald-500/30" 
          : isBear 
          ? "text-rose-200 bg-rose-950/40 border-rose-500/30" 
          : "text-amber-200 bg-amber-950/30 border-amber-500/20"
      }`}>
        <span className="font-bold flex items-center gap-0.5">
          🎯 Target:
        </span>
        <span className="font-extrabold">
          {formatUsd(targetPrice)}{" "}
          <span className={changePct >= 0 ? "text-emerald-400" : "text-rose-400"}>
            ({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)
          </span>
        </span>
      </div>

      {/* Line 3: 5 Classifiers Vote Consensus */}
      <div className="flex items-center justify-between text-[9.5px] font-mono text-slate-400 px-1">
        <span className="text-slate-500">Votes:</span>
        <span className="font-semibold text-slate-300 truncate max-w-[125px]">
          {votes}
        </span>
      </div>

      {/* Line 4: Trend State Badge & Candlestick Compression Indicators */}
      <div className="mt-0.5 flex flex-col gap-0.5">
        <span
          className={`inline-block w-full text-center rounded px-1.5 py-0.5 text-[9px] font-bold font-sans border tracking-tight leading-none ${
            isBull
              ? "bg-emerald-950/70 text-emerald-300 border-emerald-600/60"
              : isBear
              ? "bg-rose-950/70 text-rose-300 border-rose-600/60"
              : "bg-slate-900 text-slate-400 border-slate-700"
          }`}
        >
          {h.trend_label || (isBull ? "🟢 BULLISH" : isBear ? "🔴 BEARISH" : "🟡 CONSOLIDATION")}
        </span>
        {(h.is_inside_bar || h.is_nr7 || h.is_coiling_squeeze) && (
          <div className="flex items-center justify-center gap-1 mt-0.5">
            {h.is_inside_bar && (
              <span className="text-[7.5px] font-mono px-1 py-0.2 rounded bg-amber-950/80 text-amber-300 border border-amber-600/40" title="Inside Bar Compression">
                IB
              </span>
            )}
            {h.is_nr7 && (
              <span className="text-[7.5px] font-mono px-1 py-0.2 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-600/40" title="Narrow Range 7 (Maximum Volatility Contraction)">
                NR7
              </span>
            )}
            {h.is_coiling_squeeze && !h.is_nr7 && (
              <span className="text-[7.5px] font-mono px-1 py-0.2 rounded bg-purple-950/80 text-purple-300 border border-purple-600/40" title="Spring-Loaded Coiling Squeeze">
                SQUEEZE
              </span>
            )}
          </div>
        )}
      </div>

      {/* Line 5: Institutional Order Block (OB) Active Touch Badge */}
      {h.order_block_touch ? (
        <div
          className={`mt-1 flex items-center justify-between px-1.5 py-0.5 rounded border text-[9px] font-mono font-bold animate-pulse shadow-sm ${
            h.order_block_type === "BULLISH_OB"
              ? "bg-emerald-950/90 text-emerald-300 border-emerald-500 shadow-emerald-900/40"
              : "bg-rose-950/90 text-rose-300 border-rose-500 shadow-rose-900/40"
          }`}
          title={`🎯 INSTITUTIONAL ORDER BLOCK ACTIVE TOUCH\nRank: ${h.order_block_rank_label || `Rank ${h.order_block_rank || 1}`}\nZone: ${h.order_block_zone || ""}\nTouch: ${h.order_block_touch_type || "PROXIMAL_TOUCH"}`}
        >
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-ping" />
            <span>🎯 OB TOUCH [R{h.order_block_rank || 1}]</span>
          </span>
          <span className="text-[8px] opacity-80 uppercase tracking-tighter">
            {h.order_block_touch_type === "MEAN_THRESHOLD_50" ? "50% EQ" : (h.order_block_touch_type || "TEST")}
          </span>
        </div>
      ) : h.total_order_blocks && Number(h.total_order_blocks) > 0 ? (
        <div
          className="mt-0.5 flex items-center justify-between text-[8.5px] font-mono text-slate-500 px-1 hover:text-slate-400 transition-colors"
          title={`${h.total_order_blocks} active institutional order blocks monitored on this timeframe`}
        >
          <span className="flex items-center gap-0.5">
            <span>🏛️</span>
            <span>{h.total_order_blocks} OBs</span>
          </span>
          {h.order_block_zone && (
            <span className="truncate max-w-[95px] text-[7.5px] opacity-75">
              {h.order_block_zone}
            </span>
          )}
        </div>
      ) : null}
    </div>
  );
}

// Sticky Asset & Confluence Cell
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

  return (
    <td className="py-3 px-3 sm:px-4 min-w-[210px] sm:min-w-[230px] sticky-col shadow-md border-r border-slate-800/80 bg-dark-950/95">
      <div className="flex items-start gap-1.5 sm:gap-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            toggleWatchlist(item.symbol);
          }}
          className="p-1 mt-0.5 text-slate-500 hover:text-amber-400 transition-colors shrink-0"
          title={isStarred ? "Remove from Watchlist" : "Add to Watchlist"}
        >
          <Star className={`h-3.5 w-3.5 ${isStarred ? "fill-amber-400 text-amber-400" : ""}`} />
        </button>
        <div className="flex flex-col gap-1 w-full">
          {/* Confluence Tag Badge */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="rounded bg-dark-900 px-1.5 py-0.5 text-[9.5px] font-bold text-cyan-300 border border-slate-800 tracking-tight flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
              {confTag}
            </span>
            {item.has_order_block_touch && (
              <span
                className="rounded bg-gradient-to-r from-emerald-950/90 to-cyan-950/90 px-1.5 py-0.5 text-[9px] font-extrabold text-cyan-300 border border-cyan-500/60 shadow-sm shadow-cyan-950/50 flex items-center gap-1 animate-pulse"
                title={`Active Order Block Touch on Horizons: ${(item.touched_order_block_horizons || []).join(", ")}`}
              >
                <span>🎯</span>
                <span>OB TOUCH</span>
              </span>
            )}
            {idx === 0 && (
              <span className="inline-flex items-center gap-1 rounded bg-amber-950/80 px-1 py-0.5 text-[9px] font-bold text-amber-300 border border-amber-500/50">
                🥇 TOP
              </span>
            )}
          </div>

          {/* Symbol & Live Spot Price */}
          <div className="flex items-baseline justify-between gap-1">
            <span className="text-sm font-black text-white tracking-wide group-hover:text-cyan-300 transition-colors">
              {item.symbol}
            </span>
            <span className="text-xs font-mono font-bold text-slate-200">
              {formatUsd(livePrice)}
            </span>
          </div>

          {/* 24h Volume & 24h Change */}
          <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
            <span>Vol: ${((item.volume_24h_usd || 0) / 1e6).toFixed(1)}M</span>
            <span className={(item.change_24h_pct || 0) >= 0 ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>
              {(item.change_24h_pct || 0) >= 0 ? "+" : ""}{(item.change_24h_pct || 0).toFixed(2)}%
            </span>
          </div>

          {/* Timestamp sync */}
          <span className="text-[9px] text-slate-500 font-mono flex items-center gap-1">
            <Clock className="h-2.5 w-2.5 text-slate-500" />
            {relTime}
          </span>
        </div>
      </div>
    </td>
  );
}

// Full 9-Horizon Row Component
const AssetFull9HorizonsRow = React.memo(function AssetFull9HorizonsRow({
  item,
  idx,
  livePrice,
  confTag,
  isStarredFn,
  toggleWatchlist,
  activeSortKey,
  sortOrder,
  serverPredictionTimeFallback,
  onSelectCoin,
}: {
  item: any;
  idx: number;
  livePrice: number;
  confTag: string;
  isStarredFn: (s: string) => boolean;
  toggleWatchlist: (s: string) => void;
  activeSortKey: string;
  sortOrder: BiasSortOrder;
  serverPredictionTimeFallback?: string;
  onSelectCoin: (symbol: string, price: number) => void;
}) {
  const ta = item.trend_alignment || {};
  const alignRatio = item.alignment_ratio || ta.alignment_ratio || "0/9";
  const alignScore = item.alignment_score ?? ta.alignment_score_pct ?? 0;
  const bullCount = item.confluence_bull_count ?? (ta.bullish_horizons || []).length;
  const bearCount = item.confluence_bear_count ?? (ta.bearish_horizons || []).length;

  return (
    <tr
      id={`asset-row-${item.symbol.replace("/", "_")}`}
      onClick={() => onSelectCoin(item.symbol, livePrice)}
      className="matrix-row-virtual hover:bg-slate-800/60 cursor-pointer transition-colors group"
      title="Click to view historical signal records for this coin"
    >
      <AssetConfluenceCell
        item={item}
        livePrice={livePrice}
        confTag={confTag}
        isStarred={isStarredFn(item.symbol)}
        toggleWatchlist={toggleWatchlist}
        idx={idx}
        serverPredictionTimeFallback={serverPredictionTimeFallback}
      />

      {/* Render all 9 user-requested Multihorizon columns */}
      {ALL_9_HORIZONS.map((hDef) => {
        const tfData = getTimeframeData(item, hDef);
        const isCurrentSortCol = activeSortKey === hDef.key && sortOrder !== "none";
        return (
          <td
            key={hDef.key}
            className={`py-2 px-2 transition-colors ${
              isCurrentSortCol ? "bg-cyan-950/20 border-x border-cyan-500/20" : ""
            }`}
          >
            {renderMultiHorizonCell(tfData, livePrice)}
          </td>
        );
      })}

      {/* Multi-Alignment & Status Column */}
      <td className="py-3 px-4 text-right font-sans">
        <div className="flex flex-col items-end gap-1 min-w-[130px]">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-black border ${
              bullCount >= ALL_9_HORIZONS.length
                ? "bg-emerald-950/80 text-emerald-300 border-emerald-500/60"
                : bearCount >= ALL_9_HORIZONS.length
                ? "bg-rose-950/80 text-rose-300 border-rose-500/60"
                : bullCount >= 2
                ? "bg-emerald-950/40 text-emerald-400 border-emerald-500/30"
                : bearCount >= 2
                ? "bg-rose-950/40 text-rose-400 border-rose-500/30"
                : "bg-slate-900/90 text-slate-400 border-slate-800"
            }`}
          >
            <Activity className="h-3 w-3" />
            {alignRatio} ({alignScore}%)
          </span>
          {item.archetype === "ARCHETYPE_B_COILING_BREAKOUT" ? (
            <span className="text-[9px] font-black font-mono text-cyan-300 bg-cyan-950/80 px-1.5 py-0.2 rounded border border-cyan-500/40" title={item.matrix_rationale}>
              ⚡ COIL BREAKOUT
            </span>
          ) : item.archetype === "ARCHETYPE_C_RANGE_ROTATION" ? (
            <span className="text-[9px] font-black font-mono text-amber-300 bg-amber-950/80 px-1.5 py-0.2 rounded border border-amber-500/40" title={item.matrix_rationale}>
              ⚖️ RANGE ROTATION
            </span>
          ) : item.archetype === "ARCHETYPE_A_SECULAR_EXPANSION" ? (
            <span className="text-[9px] font-black font-mono text-emerald-300 bg-emerald-950/80 px-1.5 py-0.2 rounded border border-emerald-500/40" title={item.matrix_rationale}>
              💎 SECULAR TREND
            </span>
          ) : null}
          <span className={`text-[10px] font-mono font-bold ${
            item.is_ntz_active || (item.signal_status && item.signal_status.includes("NO_TRADE_ZONE"))
              ? "text-amber-400 font-black"
              : item.signal_status === "ACTIVE_SIGNAL" || item.is_trade_active
              ? "text-emerald-400 animate-pulse"
              : "text-slate-500"
          }`}>
            {item.is_ntz_active || (item.signal_status && item.signal_status.includes("NO_TRADE_ZONE"))
              ? "🛑 NO TRADE ZONE"
              : item.signal_status === "ACTIVE_SIGNAL" || item.is_trade_active
              ? "🎯 ACTIVE SIGNAL"
              : "WAITING ALIGN"}
          </span>
        </div>
      </td>
    </tr>
  );
});

// Single Horizon Focused Deep Dive Row
const AssetSingleHorizonRow = React.memo(function AssetSingleHorizonRow({
  item,
  idx,
  livePrice,
  confTag,
  isStarredFn,
  toggleWatchlist,
  selectedHorizon,
  serverPredictionTimeFallback,
  onSelectCoin,
}: {
  item: any;
  idx: number;
  livePrice: number;
  confTag: string;
  isStarredFn: (s: string) => boolean;
  toggleWatchlist: (s: string) => void;
  selectedHorizon: string;
  serverPredictionTimeFallback?: string;
  onSelectCoin: (symbol: string, price: number) => void;
}) {
  const hDef = ALL_9_HORIZONS.find((h) => h.key === selectedHorizon) || ALL_9_HORIZONS[1];
  const h = getTimeframeData(item, hDef);

  const stance = getHorizonStance(h);
  const isLong = stance === "bullish";
  const conv = h.consensus_probability !== undefined ? (h.consensus_probability * 100) : (h.conviction ?? 50.0);
  const metaProb = h.meta_win_prob_pct !== undefined ? Number(h.meta_win_prob_pct) : 75.0;
  const curr = livePrice > 0 ? livePrice : (Number(h.current_price) || 1.0);
  const targetPrice = Number(h.predicted_target_price || h.tp1_price || (isLong ? curr * 1.01 : curr * 0.99));
  const changePct = h.predicted_change_pct !== undefined ? Number(h.predicted_change_pct) : (curr > 0 ? ((targetPrice - curr) / curr) * 100 : 0.0);

  return (
    <tr
      id={`asset-row-${item.symbol.replace("/", "_")}`}
      onClick={() => onSelectCoin(item.symbol, livePrice)}
      className="matrix-row-virtual hover:bg-slate-800/60 cursor-pointer transition-colors group"
      title="Click to view historical signal records for this coin"
    >
      <AssetConfluenceCell
        item={item}
        livePrice={livePrice}
        confTag={confTag}
        isStarred={isStarredFn(item.symbol)}
        toggleWatchlist={toggleWatchlist}
        idx={idx}
        serverPredictionTimeFallback={serverPredictionTimeFallback}
      />

      <td className="py-3 px-4">
        <span className={`inline-flex items-center gap-1 font-bold ${isLong ? "text-emerald-400" : stance === "bearish" ? "text-rose-400" : "text-amber-300"}`}>
          {isLong ? "🟢 LONG" : stance === "bearish" ? "🔴 SHORT" : "🟡 CHOP"}
        </span>
      </td>

      <td className="py-3 px-4 font-mono">
        <span className="text-slate-300 font-bold">{conv.toFixed(1)}%</span>
      </td>

      <td className="py-3 px-4 font-mono">
        <span className="text-purple-300 font-bold bg-purple-950/80 px-2 py-0.5 rounded border border-purple-500/40">
          🧠 {metaProb.toFixed(1)}%
        </span>
      </td>

      <td className="py-3 px-4 font-mono text-emerald-400 font-bold">
        {formatUsd(targetPrice)} ({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)
      </td>

      <td className="py-3 px-4 font-mono text-rose-400 font-bold">
        {formatUsd(h.sl_price || (isLong ? curr * 0.985 : curr * 1.015))}
      </td>

      <td className="py-3 px-4 font-mono">
        <span className="text-slate-300">{h.classifier_votes || "4/5 CONSENSUS"}</span>
      </td>

      <td className="py-3 px-4 text-right">
        <span className={`inline-block rounded px-2 py-1 text-[10px] font-bold border ${
          isLong ? "bg-emerald-950/80 text-emerald-300 border-emerald-600/80" : stance === "bearish" ? "bg-rose-950/80 text-rose-300 border-rose-600/80" : "bg-slate-900 text-slate-400 border-slate-700"
        }`}>
          {h.trend_label || (isLong ? "🟢 BULLISH" : stance === "bearish" ? "🔴 BEARISH" : "🟡 CONSOLIDATION")}
        </span>
      </td>
    </tr>
  );
});

// ============================================================================
// MAIN COMPONENT: ASSET PREDICTION MATRIX
// ============================================================================
export default function AssetPredictionMatrix() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: status } = useStatusQuery();
  const { data: livePricesData } = useLivePricesQuery();
  const livePrices = useMemo(() => livePricesData?.prices || {}, [livePricesData?.prices]);
  const { isStarred, toggleWatchlist, watchlist } = useWatchlist();

  const [selectedHorizon, setSelectedHorizon] = useState<HorizonFilterKey>("all");
  const [search, setSearch] = useState("");
  const [selectedCoin, setSelectedCoin] = useState<{ symbol: string; price?: number } | null>(null);

  const serverSyncRelative = useRelativeTime(forecast?.server_prediction_time || forecast?.timestamp);
  const serverSyncTimeFormatted = formatServerPredictionTime(forecast?.server_prediction_time || forecast?.timestamp);

  // User-configurable Horizon Stance Sorting & Filtering
  const [sortHorizon, setSortHorizon] = useState<string>("15m");
  const [sortOrder, setSortOrder] = useState<BiasSortOrder>("none");
  const [biasFilter, setBiasFilter] = useState<BiasFilter>("all");

  const activeSortKey = sortHorizon || "15m";

  // Raw leaderboard from forecast endpoint
  const rawLeaderboard = useMemo(
    () => (forecast?.scanner_leaderboard || []).filter((item: any) => isValidCryptoSymbol(item.symbol)),
    [forecast?.scanner_leaderboard]
  );

  // Stance counts for the active sort horizon
  const stanceCounts = useMemo(() => {
    let bull = 0;
    let cons = 0;
    let bear = 0;
    const currentHDef = ALL_9_HORIZONS.find((h) => h.key === activeSortKey) || ALL_9_HORIZONS[1];
    for (const item of rawLeaderboard) {
      const tfData = getTimeframeData(item, currentHDef);
      const st = getHorizonStance(tfData);
      if (st === "bullish") bull++;
      else if (st === "bearish") bear++;
      else cons++;
    }
    return { bull, cons, bear, total: rawLeaderboard.length };
  }, [rawLeaderboard, activeSortKey]);

  // Handle column header click: cycles Bullish First -> Bearish First -> Consolidate First -> Reset
  const handleColumnHeaderSort = useCallback((horizonKey: string) => {
    if (sortHorizon !== horizonKey) {
      setSortHorizon(horizonKey);
      setSortOrder("bullish_first");
    } else {
      if (sortOrder === "none") setSortOrder("bullish_first");
      else if (sortOrder === "bullish_first") setSortOrder("bearish_first");
      else if (sortOrder === "bearish_first") setSortOrder("consolidate_first");
      else setSortOrder("none");
    }
  }, [sortHorizon, sortOrder]);

  const handleResetSort = useCallback(() => {
    setSortOrder("none");
    setBiasFilter("all");
    setSortHorizon("15m");
    setSelectedHorizon("all");
    setSearch("");
  }, []);

  // Filter and sort assets
  const filteredAssets = useMemo(() => {
    let list = [...rawLeaderboard];

    // Search query filter
    if (search.trim()) {
      const q = search.trim().toUpperCase();
      list = list.filter((item: any) => item.symbol && item.symbol.toUpperCase().includes(q));
    }

    // Watchlist tab filter
    if (selectedHorizon === "watchlist") {
      list = list.filter((item: any) => isStarred(item.symbol));
    } else if (selectedHorizon === "order_blocks") {
      list = list.filter((item: any) => item.has_order_block_touch);
    } else if (selectedHorizon === "high_confluence") {
      list = list.filter((item: any) => {
        const alignScore = item.alignment_score ?? (item.trend_alignment?.alignment_score_pct ?? 0);
        return alignScore >= 66.0 || item.is_triple_confluence;
      });
    } else if (ALL_9_HORIZONS.some((h) => h.key === selectedHorizon)) {
      const targetHDef = ALL_9_HORIZONS.find((h) => h.key === selectedHorizon);
      if (targetHDef) {
        list.sort((a: any, b: any) => {
          const stA = getHorizonStance(getTimeframeData(a, targetHDef));
          const stB = getHorizonStance(getTimeframeData(b, targetHDef));
          const scoreA = stA !== "consolidate" ? 2 : 0;
          const scoreB = stB !== "consolidate" ? 2 : 0;
          return scoreB - scoreA;
        });
      }
    }

    // Stance filter based on active sort horizon
    if (biasFilter !== "all") {
      const currentHDef = ALL_9_HORIZONS.find((h) => h.key === activeSortKey) || ALL_9_HORIZONS[1];
      list = list.filter((item: any) => {
        const tfData = getTimeframeData(item, currentHDef);
        return getHorizonStance(tfData) === biasFilter;
      });
    }

    // Sorting
    if (sortOrder !== "none") {
      const currentHDef = ALL_9_HORIZONS.find((h) => h.key === activeSortKey) || ALL_9_HORIZONS[1];
      list.sort((a: any, b: any) => {
        const aStarred = isStarred(a.symbol);
        const bStarred = isStarred(b.symbol);
        if (aStarred && !bStarred) return -1;
        if (!aStarred && bStarred) return 1;

        const stA = getHorizonStance(getTimeframeData(a, currentHDef));
        const stB = getHorizonStance(getTimeframeData(b, currentHDef));

        const getRank = (st: string) => {
          if (sortOrder === "bullish_first") return st === "bullish" ? 0 : st === "consolidate" ? 1 : 2;
          if (sortOrder === "bearish_first") return st === "bearish" ? 0 : st === "consolidate" ? 1 : 2;
          return st === "consolidate" ? 0 : st === "bullish" ? 1 : 2;
        };
        return getRank(stA) - getRank(stB);
      });
    } else {
      // Default: Starred on top, followed by algorithmic ranking
      list.sort((a: any, b: any) => {
        const aStarred = isStarred(a.symbol);
        const bStarred = isStarred(b.symbol);
        if (aStarred && !bStarred) return -1;
        if (!aStarred && bStarred) return 1;
        return 0;
      });
    }

    return list;
  }, [rawLeaderboard, search, selectedHorizon, isStarred, activeSortKey, sortOrder, biasFilter]);

  // Horizon Filter Tabs
  const horizonTabs: { key: HorizonFilterKey; label: string }[] = useMemo(
    () => [
      { key: "all", label: "🌐 Multi-Horizon (15M, 1H, 4H)" },
      { key: "order_blocks", label: "🎯 OB Touches" },
      { key: "15m", label: "⚡ 15M Execution" },
      { key: "1h", label: "⏳ 1H Intraday" },
      { key: "4h", label: "⏳ 4H Macro Anchor" },
      { key: "high_confluence", label: "💎 High Confluence" },
      { key: "watchlist", label: `⭐ Watchlist (${watchlist.length})` },
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

      {/* Header */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2.5 flex-wrap">
            <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
              <Compass className="h-5 w-5 text-cyan-400" />
              Multi-Horizon Matrix (15M, 1H, 4H)
            </h2>
            <span className="rounded-md bg-dark-900 px-2.5 py-0.5 text-xs font-semibold text-cyan-300 border border-cyan-700/50">
              {filteredAssets.length} of {rawLeaderboard.length || 40} Coins
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-bold text-emerald-400 border border-emerald-500/30">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
              SERVER SYNC: {serverSyncRelative}
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Institutional AI prediction matrix showing next candle direction (Green Bullish / Red Bearish), 5 Classifiers + 5 Regressors consensus, and Secondary ML Meta-Labelers across 15M, 1H, and 4H timeframes (15M Execution Only).{" "}
            <span className="text-cyan-400 font-semibold underline decoration-dotted">
              Click any column header to sort by that timeframe.
            </span>
          </p>
        </div>
      </div>

      {/* Horizon Filter Tabs & Search */}
      <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-1 rounded-xl bg-dark-900/90 p-1 border border-slate-800 overflow-x-auto max-w-full">
          {horizonTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => {
                setSelectedHorizon(tab.key);
                if (ALL_9_HORIZONS.some((h) => h.key === tab.key)) {
                  setSortHorizon(tab.key);
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
            placeholder="Search 40 curated pairs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-xl bg-dark-900/90 pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 border border-slate-800 focus:border-cyan-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Stance Sorting & Filtering Toolbar */}
      <div className="mt-3.5 flex flex-col gap-2.5 rounded-xl bg-dark-900/80 p-3 border border-slate-800/90 shadow-inner">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3">
          {/* Target Horizon Sorter Selection */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <SlidersHorizontal className="h-3.5 w-3.5 text-cyan-400" />
              Active Sort Horizon:
            </span>
            <div className="flex items-center gap-1 bg-dark-950/90 p-1 rounded-lg border border-slate-800 flex-wrap">
              {ALL_9_HORIZONS.map((h) => (
                <button
                  key={h.key}
                  type="button"
                  onClick={() => setSortHorizon(h.key)}
                  className={`px-2 py-0.5 text-xs font-bold rounded-md transition-all ${
                    activeSortKey === h.key
                      ? "bg-cyan-500/25 text-cyan-200 border border-cyan-500/40 shadow-sm"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                  }`}
                  title={h.desc}
                >
                  {h.short}
                </button>
              ))}

              <button
                type="button"
                onClick={handleResetSort}
                className="flex items-center gap-1 px-2.5 py-0.5 text-xs font-bold rounded-md bg-slate-800/70 text-slate-300 border border-slate-700 hover:text-white transition-all ml-1"
                title="Reset sorting and filters"
              >
                <RotateCcw className="h-3 w-3 text-cyan-400" />
                <span>Reset</span>
              </button>
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
                onClick={() => setSortOrder("none")}
                className={`px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                  sortOrder === "none"
                    ? "bg-cyan-500/25 text-cyan-200 border border-cyan-500/40 shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Default Rank
              </button>
              <button
                type="button"
                onClick={() => setSortOrder("bullish_first")}
                className={`flex items-center gap-1 px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                  sortOrder === "bullish_first"
                    ? "bg-emerald-950/90 text-emerald-300 border border-emerald-500/60 shadow-sm"
                    : "text-emerald-400/80 hover:text-emerald-300"
                }`}
              >
                <span>Bullish First</span>
                {sortOrder === "bullish_first" && <ArrowUp className="h-3 w-3 text-emerald-400" />}
              </button>
              <button
                type="button"
                onClick={() => setSortOrder("bearish_first")}
                className={`flex items-center gap-1 px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                  sortOrder === "bearish_first"
                    ? "bg-rose-950/90 text-rose-300 border border-rose-500/60 shadow-sm"
                    : "text-rose-400/80 hover:text-rose-300"
                }`}
              >
                <span>Bearish First</span>
                {sortOrder === "bearish_first" && <ArrowDown className="h-3 w-3 text-rose-400" />}
              </button>
            </div>
          </div>
        </div>

        {/* Quick Stance Filter Chips */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-t border-slate-800/70 pt-2 text-xs">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
              Filter Stance:
            </span>
            <button
              type="button"
              onClick={() => setBiasFilter("all")}
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition-all ${
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
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition-all ${
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
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition-all ${
                biasFilter === "consolidate"
                  ? "bg-slate-800 text-slate-200 border border-slate-600 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              🟡 Consolidate ({stanceCounts.cons})
            </button>
            <button
              type="button"
              onClick={() => setBiasFilter("bearish")}
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition-all ${
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
              <span className="text-cyan-300 font-semibold flex items-center gap-1 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-700/40">
                <span>Active Sort:</span>
                <strong className="text-white">
                  {ALL_9_HORIZONS.find((h) => h.key === activeSortKey)?.short}
                </strong>
                <span>➔</span>
                <span className="capitalize text-cyan-200">{sortOrder.replace("_first", "")} First</span>
              </span>
            ) : (
              <span className="text-slate-500">
                Sorted by: Default Institutional Ranking (#1 to #{rawLeaderboard.length})
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 9-Horizon Matrix Table Container */}
      <div className="mt-4 overflow-x-auto touch-scroll rounded-xl border border-slate-800/80 shadow-inner">
        <table className="w-full text-left text-xs text-slate-300 font-mono">
          <thead className="bg-dark-900/95 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="py-3 px-3 sm:px-4 min-w-[210px] sm:min-w-[230px] sticky-col shadow-md border-r border-slate-800/80 bg-dark-900/95">
                # / Asset &amp; Confluence
              </th>

              {selectedHorizon === "all" || selectedHorizon === "high_confluence" || selectedHorizon === "watchlist" ? (
                <>
                  {/* All 9 Timeframe Columns Requested by User */}
                  {ALL_9_HORIZONS.map((hDef) => {
                    const isSorted = activeSortKey === hDef.key && sortOrder !== "none";
                    return (
                      <th
                        key={hDef.key}
                        onClick={() => handleColumnHeaderSort(hDef.key)}
                        className={`py-3 px-3 min-w-[170px] cursor-pointer select-none transition-all group ${
                          isSorted
                            ? "bg-cyan-950/50 text-cyan-200 border-b-2 border-cyan-400"
                            : "hover:bg-slate-800/80 text-slate-300"
                        }`}
                        title={`${hDef.label} - ${hDef.desc}\nClick to cycle sort`}
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="font-bold tracking-tight">{hDef.label}</span>
                          <div className="shrink-0 flex items-center">
                            {isSorted ? (
                              sortOrder === "bullish_first" ? (
                                <span className="inline-flex items-center gap-0.5 bg-emerald-950 text-emerald-300 px-1 py-0.5 rounded text-[8.5px] font-black border border-emerald-500/50">
                                  <ArrowUp className="h-2 w-2" /> Bull
                                </span>
                              ) : sortOrder === "bearish_first" ? (
                                <span className="inline-flex items-center gap-0.5 bg-rose-950 text-rose-300 px-1 py-0.5 rounded text-[8.5px] font-black border border-rose-500/50">
                                  <ArrowDown className="h-2 w-2" /> Bear
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-0.5 bg-slate-800 text-slate-200 px-1 py-0.5 rounded text-[8.5px] font-black border border-slate-600">
                                  <CircleDot className="h-2 w-2" /> Chop
                                </span>
                              )
                            ) : (
                              <ArrowUpDown className="h-3 w-3 text-slate-600 group-hover:text-slate-300 transition-colors" />
                            )}
                          </div>
                        </div>
                      </th>
                    );
                  })}
                  <th className="py-3 px-4 text-right min-w-[130px]">Multi-Alignment</th>
                </>
              ) : (
                <>
                  {/* Single Horizon Deep Dive Columns */}
                  <th className="py-3 px-4 min-w-[120px]">Predicted Direction</th>
                  <th className="py-3 px-4 min-w-[100px]">Conviction %</th>
                  <th className="py-3 px-4 min-w-[120px]">🧠 ML Win Prob</th>
                  <th className="py-3 px-4 min-w-[140px]">Target Price (% Chg)</th>
                  <th className="py-3 px-4 min-w-[120px]">Invalidation SL</th>
                  <th className="py-3 px-4 min-w-[130px]">Classifier Votes</th>
                  <th className="py-3 px-4 text-right min-w-[130px]">Trend State</th>
                </>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
            {isLoading && rawLeaderboard.length === 0 ? (
              <tr>
                <td colSpan={11} className="py-12 text-center text-slate-500 font-sans">
                  Loading Curated Top 40 asset predictions across 9 horizons...
                </td>
              </tr>
            ) : filteredAssets.length === 0 ? (
              <tr>
                <td colSpan={11} className="py-12 text-center font-sans">
                  <div className="flex flex-col items-center justify-center gap-3">
                    <SlidersHorizontal className="h-8 w-8 text-slate-600" />
                    <p className="text-slate-400 font-medium text-sm">
                      No assets match the selected filter{biasFilter !== "all" ? ` (${biasFilter} stance)` : ""}{search ? ` matching "${search}"` : ""}.
                    </p>
                    <button
                      onClick={handleResetSort}
                      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-cyan-600/20 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-600/30 text-xs font-semibold transition-all shadow-sm cursor-pointer"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      Reset All Filters &amp; View All 40 Assets
                    </button>
                  </div>
                </td>
              </tr>
            ) : (
              filteredAssets.map((item: any, idx: number) => {
                const confTag = item.confluence_tag || `Score: ${item.alignment_score ?? 0}%`;
                const livePrice = livePrices[item.symbol] || livePrices[item.symbol.replace('/', '')] || item.current_price;
                const fallbackTime = forecast?.server_prediction_time || forecast?.timestamp;

                // Single-Horizon view
                if (
                  selectedHorizon !== "all" &&
                  selectedHorizon !== "high_confluence" &&
                  selectedHorizon !== "watchlist"
                ) {
                  return (
                    <AssetSingleHorizonRow
                      key={item.symbol}
                      item={item}
                      idx={idx}
                      livePrice={livePrice}
                      confTag={confTag}
                      isStarredFn={isStarred}
                      toggleWatchlist={toggleWatchlist}
                      selectedHorizon={selectedHorizon}
                      serverPredictionTimeFallback={fallbackTime}
                      onSelectCoin={(sym, price) => setSelectedCoin({ symbol: sym, price })}
                    />
                  );
                }

                // Full 9-Horizon Matrix Row
                return (
                  <AssetFull9HorizonsRow
                    key={item.symbol}
                    item={item}
                    idx={idx}
                    livePrice={livePrice}
                    confTag={confTag}
                    isStarredFn={isStarred}
                    toggleWatchlist={toggleWatchlist}
                    activeSortKey={activeSortKey}
                    sortOrder={sortOrder}
                    serverPredictionTimeFallback={fallbackTime}
                    onSelectCoin={(sym, price) => setSelectedCoin({ symbol: sym, price })}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
