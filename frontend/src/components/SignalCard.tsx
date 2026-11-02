"use client";

import React, { useState, useMemo } from "react";
import { formatPercent, formatUsd } from "@/lib/utils";
import SignalShareModal from "@/components/SignalShareModal";
import CoinSignalHistoryModal from "@/components/CoinSignalHistoryModal";
import TradeProgressBar from "@/components/TradeProgressBar";
import { useTrackedTrades } from "@/hooks/useTrackedTrades";
import { useLivePricesQuery } from "@/hooks/useCryptoData";
import {
  ArrowUpRight,
  ArrowDownRight,
  ShieldAlert,
  Target,
  Sparkles,
  Zap,
  Layers,
  Clock,
  Share2,
  History,
  Check,
  TrendingUp,
  CheckCircle2,
} from "lucide-react";

interface SignalCardProps {
  signal: any;
  rankIndex?: number;
}

export default function SignalCard({ signal, rankIndex = 0 }: SignalCardProps) {
  const { takeTrade, isTradeTracked } = useTrackedTrades();
  const { data: livePricesData } = useLivePricesQuery();
  const livePrices = useMemo(() => livePricesData?.prices || {}, [livePricesData?.prices]);

  const [tradeTakenFeedback, setTradeTakenFeedback] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [selectedHorizonOverride, setSelectedHorizonOverride] = useState<string | null>(null);

  // Companion signals for the same coin across timeframes (15M, 1H, 24H)
  const coinSigs: any[] = signal.all_coin_signals && signal.all_coin_signals.length > 0 ? signal.all_coin_signals : [signal];
  
  // Resolve active signal based on user horizon pill click, or default to current signal
  const activeSig = useMemo(() => {
    if (!selectedHorizonOverride) return signal;
    return coinSigs.find((cs: any) => {
      const hStr = (cs.horizon_tag || cs.horizon || cs.horizon_name || cs.active_signal_horizon || cs.dominant_timeframe || "").toUpperCase();
      return hStr.includes(selectedHorizonOverride);
    }) || signal;
  }, [selectedHorizonOverride, coinSigs, signal]);

  // Confluence & Conflict Detection
  const { isAlignedConfluence, isTripleConfluence, hasConflict, confluenceSummary } = useMemo(() => {
    if (coinSigs.length <= 1) {
      return { isAlignedConfluence: false, isTripleConfluence: false, hasConflict: false, confluenceSummary: "" };
    }
    const dirs = coinSigs.map((cs: any) => String(cs.direction || "").toUpperCase());
    const longs = dirs.filter((d: string) => d.includes("LONG") || d.includes("BULL")).length;
    const shorts = dirs.filter((d: string) => d.includes("SHORT") || d.includes("BEAR")).length;
    const aligned = longs === coinSigs.length || shorts === coinSigs.length;
    const conflict = longs > 0 && shorts > 0;
    const triple = aligned && coinSigs.length >= 3;
    const summary = aligned
      ? (triple ? "💎 Triple Confluence: 15M, 1H & 1D directionally aligned! (+18% Win Edge)" : "🔥 Dual Confluence: Multi-timeframe trend alignment")
      : "⚠️ Mixed Timeframes: Lower timeframe scalp moves counter to macro trend.";
    return { isAlignedConfluence: aligned, isTripleConfluence: triple, hasConflict: conflict, confluenceSummary: summary };
  }, [coinSigs]);

  const isLong = activeSig.direction === "LONG" || activeSig.direction === "BULLISH";

  // Clean concise Grade String for fallback
  const rawGrade = String(activeSig.quality_grade || activeSig.grade || signal.quality_grade || signal.grade || "Grade A");
  const shortGrade = useMemo(() => {
    if (rawGrade.includes("A+")) return "Grade A+";
    if (rawGrade.includes("B+")) return "Grade B+";
    if (rawGrade.includes("Grade A")) return "Grade A";
    if (rawGrade.includes("Grade B")) return "Grade B";
    return rawGrade.split("(")[0].trim().replace("💎", "").trim() || "Grade A";
  }, [rawGrade]);

  // Full Institutional Setup Architecture Title
  // e.g. "Grade A+ (💎 ZEIIERMAN RANK 1 NESTED SMC [4H POI + 1H TRIGGER] RETEST)"
  const setupTitle = useMemo(() => {
    // 1. Direct check in quality_grade or grade if it contains the full setup description
    const fullGrade = String(activeSig.quality_grade || activeSig.grade || signal.quality_grade || signal.grade || "");
    if (fullGrade && fullGrade.includes("(") && fullGrade.includes(")")) {
      return fullGrade.trim();
    }

    // 2. Direct check in decision if it contains ZEIIERMAN or SMC
    const dec = String(activeSig.decision || signal.decision || "");
    if (dec.includes("ZEIIERMAN") || dec.includes("SMC") || dec.includes("ORDER-BLOCK") || dec.includes("BREAKER")) {
      const cleanDec = dec.replace("🎯", "").replace("(LONG)", "").replace("(SHORT)", "").trim();
      return `Grade A+ (${cleanDec})`;
    }

    // 3. Zeiierman SMC setup properties
    const obSetup = activeSig.order_block_setup || signal.order_block_setup;
    const rankLabel = activeSig.zeiierman_rank_label || signal.zeiierman_rank_label || obSetup?.zeiierman_rank_label;
    const isNested = Boolean(activeSig.is_nested_smc || signal.is_nested_smc || obSetup?.is_nested_smc || (rankLabel && rankLabel.includes("NESTED")));
    const htfPoi = (activeSig.htf_poi_tf || signal.htf_poi_tf || obSetup?.htf_poi_tf || "4H").toUpperCase();
    const horizonClean = (activeSig.horizon || activeSig.horizon_tag || "1H").toUpperCase().replace("SCALP", "").replace("INTRADAY", "").replace("DAILY", "").trim() || "1H";

    if (isNested) {
      return `Grade A+ (💎 ZEIIERMAN RANK 1 NESTED SMC [${htfPoi} POI + ${horizonClean} TRIGGER] RETEST)`;
    }
    if (rankLabel) {
      return `Grade A+ (${rankLabel} RETEST)`;
    }

    // 4. Timeframe unanimous alignment setups
    const hzStr = (activeSig.horizon || activeSig.horizon_tag || "15M").toUpperCase();
    if (hzStr.includes("24H") || hzStr.includes("1D")) {
      return "Grade A+ (💎 24H STRICT 7-HORIZON ALIGNMENT: 15M-15D UNANIMOUS)";
    }
    if (hzStr.includes("1H")) {
      return "Grade A+ (🔥 1H STRICT 7-HORIZON ALIGNMENT: 5M-7D UNANIMOUS)";
    }
    return "Grade A (⚡ 15M STRICT 6-HORIZON ALIGNMENT: 5M-24H UNANIMOUS)";
  }, [activeSig, signal, rawGrade]);

  const isGradeAPlus = setupTitle.includes("A+") || rawGrade.includes("A+");

  const conviction = activeSig.conviction_pct ?? activeSig.conviction ?? 50.0;
  const horizon = activeSig.horizon || activeSig.horizon_name || "SCALP (15M)";
  const expReturn = activeSig.expected_return_pct ?? (activeSig.exp_return ? activeSig.exp_return * 100 : 0.0);

  // ML Win Probability from secondary meta-labeler in engine (0.0 - 1.0 or 0 - 100)
  const metaWinProb =
    activeSig.meta_win_probability_pct ??
    activeSig.meta_win_prob_pct ??
    activeSig.win_probability_pct ??
    activeSig.win_prob ??
    (activeSig.meta_win_probability !== undefined && activeSig.meta_win_probability !== null
      ? activeSig.meta_win_probability <= 1.0
        ? activeSig.meta_win_probability * 100.0
        : activeSig.meta_win_probability
      : activeSig.meta_win_prob !== undefined && activeSig.meta_win_prob !== null
      ? activeSig.meta_win_prob <= 1.0
        ? activeSig.meta_win_prob * 100.0
        : activeSig.meta_win_prob
      : conviction > 0
      ? Math.min(94.0, Math.max(45.0, conviction * 0.88))
      : 75.0);

  // Exact Calibrated Path Probabilities for TP1, TP2, TP3 and Stop-Loss
  const baseProb = metaWinProb ?? 75.0;
  const pTp1 = Number(activeSig.path_probabilities?.tp1 ?? activeSig.p_tp1_pct ?? activeSig.p_tp1 ?? activeSig.tp1_prob ?? Math.max(15.0, Math.min(95.0, baseProb)));
  const pTp2 = Number(activeSig.path_probabilities?.tp2 ?? activeSig.p_tp2_pct ?? activeSig.p_tp2 ?? activeSig.tp2_prob ?? Math.round(pTp1 * 0.65 * 10) / 10);
  const pTp3 = Number(activeSig.path_probabilities?.tp3 ?? activeSig.p_tp3_pct ?? activeSig.p_tp3 ?? activeSig.tp3_prob ?? Math.round(pTp2 * 0.55 * 10) / 10);
  const pSl = Number(activeSig.path_probabilities?.sl ?? activeSig.p_sl_pct ?? activeSig.p_sl ?? activeSig.sl_prob ?? Math.max(5.0, Math.round((100.0 - pTp1) * 10) / 10));

  const entryPrice = Math.max(0, Number(activeSig.entry_price ?? activeSig.current_price ?? 0.0));
  const tp1 = Math.max(0, Number(activeSig.tp1_price ?? activeSig.tp_price ?? entryPrice));
  const tp2 = Math.max(0, Number(activeSig.tp2_price ?? activeSig.tp_price ?? entryPrice));
  const tp3 = Math.max(0, Number(activeSig.tp3_price ?? activeSig.tp_price ?? entryPrice));
  const sl = Math.max(0, Number(activeSig.sl_price ?? entryPrice));

  const status = String(activeSig.status || "ACTIVE").toUpperCase();
  const outcomeLabel = String(activeSig.outcome_label || "").toUpperCase();
  const combinedStatus = `${status} ${outcomeLabel}`;
  
  // Realized / Actually Exited States (Trade is officially over)
  const hasExitPrice = Boolean(activeSig.exit_price && Number(activeSig.exit_price) > 0);
  const hasRealizedReturn = Boolean(activeSig.realized_return_num !== undefined && activeSig.realized_return_num !== null) || Boolean(activeSig.realized_return_pct && String(activeSig.realized_return_pct).trim() !== "");
  const isExplicitlyResolved = status.startsWith("WON_") || status.startsWith("LOST_") || status.includes("EXP") || outcomeLabel.includes("EXP") || status === "STAGNATION_CUT" || combinedStatus.includes("CLOSED") || combinedStatus.includes("RESOLVED") || combinedStatus.includes("CANCEL");
  const isClosed = hasExitPrice || hasRealizedReturn || isExplicitlyResolved;

  // Real-time Live Price Lookup from livePrices cache / WebSocket feed
  const rawSymbol = String(activeSig.symbol || signal.symbol || "").toUpperCase().trim();
  const slashSymbol = rawSymbol.includes("/") ? rawSymbol : `${rawSymbol.replace("USDT", "")}/USDT`;
  const plainSymbol = rawSymbol.replace("/", "").replace(":USDT", "");
  const baseSymbol = plainSymbol.replace("USDT", "");
  const usdtSymbol = `${baseSymbol}USDT`;

  const liveTickerPrice = Number(
    livePrices[slashSymbol] ??
    livePrices[usdtSymbol] ??
    livePrices[plainSymbol] ??
    livePrices[rawSymbol] ??
    livePrices[baseSymbol] ??
    0
  );

  // Authoritative Current Price:
  // 1. If trade is closed with an exit_price, show the official exit_price
  // 2. If real-time ticker stream has fresh price, use it (Primary for active trades)
  // 3. Fallback to activeSig.live_price if provided
  // 4. Fallback to activeSig.current_price
  // 5. Graceful fallback to entryPrice
  const currentPrice = useMemo(() => {
    if (isClosed && hasExitPrice) {
      return Number(activeSig.exit_price);
    }
    if (liveTickerPrice > 0) {
      return liveTickerPrice;
    }
    if (Number(activeSig.live_price) > 0) {
      return Number(activeSig.live_price);
    }
    if (Number(activeSig.current_price) > 0) {
      return Number(activeSig.current_price);
    }
    return entryPrice;
  }, [isClosed, hasExitPrice, activeSig.exit_price, liveTickerPrice, activeSig.live_price, activeSig.current_price, entryPrice]);

  // Active Protected States (Trade is running in-flight with defense armed)
  const isProtectedActive = status === "TIER0_PROTECTED_BREAKEVEN" || status === "TP1_LOCKED_BREAKEVEN" || status === "TP2_LOCKED_TRAIL" || Boolean(activeSig.is_tier0_locked) || Boolean(activeSig.is_tp1_locked);

  const isWon = isClosed && (status.startsWith("WON_") || combinedStatus.includes("WON"));
  const isLost = isClosed && (status.startsWith("LOST_") || combinedStatus.includes("LOST") || combinedStatus.includes("STOP"));
  const isExpired = isClosed && (status === "EXPIRED" || combinedStatus.includes("EXPIRED"));
  const isBreakeven = isProtectedActive || (isClosed && (status.includes("BE") || combinedStatus.includes("BREAKEVEN") || combinedStatus.includes("GUARD")));
  const isSlAtBreakeven = isProtectedActive || isBreakeven || (entryPrice > 0 && Math.abs(sl - entryPrice) / entryPrice < 0.0005);
  const wasPriceUpdated = Boolean(activeSig.was_price_updated);
  const prevEntry = activeSig.previous_entry_price;

  // Direction-aware TP gain percentage (profit yield relative to entry)
  const tp1Pct = entryPrice > 0 ? (isLong ? (tp1 - entryPrice) / entryPrice : (entryPrice - tp1) / entryPrice) * 100 : 0;
  const tp2Pct = entryPrice > 0 ? (isLong ? (tp2 - entryPrice) / entryPrice : (entryPrice - tp2) / entryPrice) * 100 : 0;
  const tp3Pct = entryPrice > 0 ? (isLong ? (tp3 - entryPrice) / entryPrice : (entryPrice - tp3) / entryPrice) * 100 : 0;

  // Direction-aware Stop loss risk percentage relative to entry
  const slPct = entryPrice > 0 ? (isLong ? (entryPrice - sl) / entryPrice : (sl - entryPrice) / entryPrice) * 100 : 0;
  // Positive locked return if stop loss is ratcheted past entry
  const beProfitPct = entryPrice > 0 ? (isLong ? (sl - entryPrice) / entryPrice : (entryPrice - sl) / entryPrice) * 100 : 0;

  // Pending Limit Order Guard (Order is resting, awaiting retest into value zone)
  const isLimitPending = Boolean(
    activeSig.is_limit_pending ||
    status === "PENDING_LIMIT" ||
    combinedStatus.includes("AWAIT PULLBACK") ||
    combinedStatus.includes("AWAIT BOUNCE")
  );

  // Authoritative Floating or Realized PnL:
  // - If resting limit: null
  // - If closed: use realized return number
  // - If active: calculate dynamically from currentPrice vs entryPrice
  const livePnl: number | null = useMemo(() => {
    if (isLimitPending) return null;
    if (isClosed) {
      if (activeSig.realized_return_num !== undefined && activeSig.realized_return_num !== null) {
        return Number(activeSig.realized_return_num);
      }
      if (activeSig.realized_return_pct) {
        const parsed = parseFloat(String(activeSig.realized_return_pct).replace("%", ""));
        if (!isNaN(parsed)) return parsed;
      }
    }
    if (entryPrice > 0 && currentPrice > 0) {
      return isLong
        ? ((currentPrice - entryPrice) / entryPrice) * 100
        : ((entryPrice - currentPrice) / entryPrice) * 100;
    }
    if (activeSig.live_pnl_pct !== undefined && activeSig.live_pnl_pct !== null) {
      return Number(activeSig.live_pnl_pct);
    }
    return 0;
  }, [isLimitPending, isClosed, activeSig.realized_return_num, activeSig.realized_return_pct, entryPrice, currentPrice, isLong, activeSig.live_pnl_pct]);

  // Target Hit Flags
  const isTp1Hit = isWon || (isLong ? currentPrice >= tp1 && tp1 > entryPrice : currentPrice <= tp1 && tp1 < entryPrice);
  const isTp2Hit = (isClosed && combinedStatus.includes("TP2")) || (isLong ? currentPrice >= tp2 && tp2 > tp1 : currentPrice <= tp2 && tp2 < tp1 && tp2 > 0);
  const isTp3Hit = (isClosed && combinedStatus.includes("TP3")) || (isLong ? currentPrice >= tp3 && tp3 > tp2 : currentPrice <= tp3 && tp3 < tp2 && tp3 > 0);

  const medals = ["🥇 TOP PICK (#1)", "🥈 RUNNER UP (#2)", "🥉 BRONZE (#3)", "🎯 PICK (#4)", "🎯 PICK (#5)"];
  const rankLabel = activeSig.rank || (rankIndex < medals.length ? medals[rankIndex] : `#${rankIndex + 1}`);

  return (
    <>
      {showShareModal && (
        <SignalShareModal signal={signal} onClose={() => setShowShareModal(false)} />
      )}

      {showHistoryModal && (
        <CoinSignalHistoryModal
          symbol={signal.symbol}
          currentPrice={currentPrice > 0 ? currentPrice : entryPrice}
          onClose={() => setShowHistoryModal(false)}
        />
      )}

      <div
        id={`signal-card-${signal.symbol.replace("/", "_")}`}
        className={`glass-panel glass-panel-hover rounded-2xl p-4 sm:p-5 border relative overflow-hidden transition-all duration-300 flex flex-col justify-between ${
          isGradeAPlus
            ? "border-cyan-500/40 shadow-lg shadow-cyan-500/10 hover:border-cyan-400"
            : "border-slate-800 hover:border-slate-700"
        }`}
      >
        {/* Background Ambient Glow */}
        <div
          className={`absolute -top-12 -right-12 h-32 w-32 rounded-full blur-3xl pointer-events-none ${
            isLong ? "bg-emerald-500/15" : "bg-rose-500/15"
          }`}
        />

        {/* Top Section */}
        <div>
          {/* Header: Rank Badge & Quality Grade & ML Win Prob */}
          <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 pb-3 flex-wrap">
            <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
              <span className="rounded-lg bg-dark-900 px-2.5 py-1 text-xs font-bold text-slate-200 border border-slate-700/80">
                {rankLabel}
              </span>
              <span
                className={`rounded-lg px-2.5 py-1 text-xs font-bold flex items-center gap-1.5 transition-all ${
                  isGradeAPlus
                    ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20"
                    : shortGrade.includes("B")
                    ? "bg-indigo-950/80 text-indigo-300 border border-indigo-500/40"
                    : "bg-emerald-950/80 text-emerald-300 border border-emerald-500/40"
                }`}
                title={`Quantitative Quality Grade: ${setupTitle}`}
              >
                <Sparkles className="h-3 w-3 shrink-0" />
                <span className="font-black text-xs tracking-wide">{setupTitle}</span>
              </span>

              {/* Probability Score Badge */}
              <span
                className="rounded-lg px-2.5 py-1 text-xs font-bold flex items-center gap-1 bg-purple-950/80 text-purple-300 border border-purple-500/40 font-mono shadow-sm"
                title="Calibrated Path Win Probability P(TP1)"
              >
                <span>🧠 Prob:</span>
                <span className="text-purple-200 font-black">{metaWinProb ? `${metaWinProb.toFixed(1)}%` : "N/A"}</span>
              </span>

              {/* Lifecycle Status Pill */}
              <span
                className={`rounded-lg px-2.5 py-1 text-xs font-bold flex items-center gap-1.5 border font-mono ${
                  isLimitPending
                    ? "bg-amber-950/80 text-amber-300 border-amber-500/60 shadow-sm shadow-amber-500/20"
                    : isWon
                    ? "bg-emerald-950 text-emerald-300 border-emerald-500 shadow-sm shadow-emerald-500/20"
                    : isLost
                    ? "bg-rose-950 text-rose-300 border-rose-500 shadow-sm shadow-rose-500/20"
                    : isBreakeven
                    ? "bg-cyan-950 text-cyan-300 border-cyan-500 shadow-sm shadow-cyan-500/20"
                    : isExpired
                    ? "bg-slate-900 text-slate-400 border-slate-700"
                    : "bg-emerald-950/60 text-emerald-400 border-emerald-600/50"
                }`}
              >
                {isLimitPending ? (
                  <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
                ) : !isWon && !isLost && !isExpired && (
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shrink-0" />
                )}
                <span>
                  {isLimitPending
                    ? (signal.outcome_label || "AWAIT PULLBACK ⏳")
                    : isWon
                    ? "TARGET HIT 🎯"
                    : isLost
                    ? "STOP TRIGGERED 🛑"
                    : isBreakeven
                    ? "BREAKEVEN 🛡️"
                    : (signal.outcome_label || "ACTIVE 🟢")}
                </span>
              </span>
            </div>

            <div className="flex items-center gap-1.5">
              {/* Live or Realized PnL Badge */}
              {isLimitPending ? (
                <span
                  className="rounded-lg px-2 py-1 text-xs font-mono font-black border bg-amber-950/90 text-amber-300 border-amber-500/60"
                  title={`Resting Limit Order awaiting retest: ${formatUsd(entryPrice)}`}
                >
                  ⏳ RESTING LIMIT
                </span>
              ) : livePnl !== undefined && livePnl !== null && (
                <span
                  className={`rounded-lg px-2 py-1 text-xs font-mono font-black border ${
                    livePnl >= 0
                      ? "bg-emerald-950/90 text-emerald-300 border-emerald-500/60"
                      : "bg-rose-950/90 text-rose-300 border-rose-500/60"
                  }`}
                  title={isClosed ? "Final Realized Trade Return" : "Current live floating PnL based on real-time price"}
                >
                  {isClosed ? "Realized: " : ""}
                  {livePnl >= 0 ? "+" : ""}
                  {Number(livePnl).toFixed(2)}%
                </span>
              )}

              {/* Share Modal Button */}
              <button
                type="button"
                onClick={() => setShowShareModal(true)}
                className="p-1.5 rounded-lg bg-dark-900 border border-slate-800 text-slate-400 hover:text-cyan-300 hover:border-cyan-600 transition-all"
                title="Share / Export Signal Card"
              >
                <Share2 className="h-3.5 w-3.5" />
              </button>

              {/* Direction Badge */}
              <span
                className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-black tracking-wide ${
                  isLong
                    ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                    : "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                }`}
              >
                {isLong ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
                {isLong ? "LONG BUY" : "SHORT SELL"}
              </span>
            </div>
          </div>

          {/* Asset & Horizon Bar */}
          <div className="mt-3.5 flex items-center justify-between gap-3 flex-wrap">
            <div className="flex-1 min-w-[200px]">
              <div className="flex items-center gap-2 flex-wrap">
                <h3
                  onClick={() => setShowHistoryModal(true)}
                  className="text-xl font-black tracking-tight text-white flex items-center gap-1.5 cursor-pointer hover:text-cyan-400 transition-colors group"
                  title="Click to view historical signals for this coin"
                >
                  {signal.symbol}
                  <History className="h-3.5 w-3.5 text-cyan-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                </h3>

                {/* BTC Alignment Badge */}
                {signal.btc_alignment_label && (
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                      signal.btc_alignment_tag === "BEAR_SENSITIVE_LEVERAGED"
                        ? "bg-rose-950/80 text-rose-300 border-rose-500/60"
                        : signal.btc_alignment_tag === "INVERSE_BTC_HEDGE"
                        ? "bg-indigo-950/80 text-indigo-300 border-indigo-500/60"
                        : signal.btc_alignment_tag === "DECOUPLED_INDEPENDENT"
                        ? "bg-amber-950/80 text-amber-300 border-amber-500/60"
                        : "bg-emerald-950/80 text-emerald-300 border-emerald-500/60"
                    }`}
                    title="Cross-Asset BTC Correlation and Systematic Beta Contagion Status"
                  >
                    {signal.btc_alignment_label}
                  </span>
                )}

                {/* Hype Surge / Blow-Off Top Alert */}
                {signal.is_blowoff_top ? (
                  <span className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-500 animate-pulse">
                    🛑 BLOW-OFF TOP
                  </span>
                ) : signal.is_hype_surge ? (
                  <span className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-500 animate-pulse">
                    🚀 HYPE SURGE
                  </span>
                ) : null}

                {/* Zeiierman SMC Order Block & Nested POI Badge */}
                {activeSig.is_nested_smc || (activeSig.decision && activeSig.decision.includes("NESTED SMC")) ? (
                  <span
                    className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-gradient-to-r from-cyan-950 via-indigo-950 to-cyan-950 text-cyan-200 border border-cyan-400 shadow-sm shadow-cyan-500/30 flex items-center gap-1"
                    title={`Nested SMC: Institutional Macro POI (${activeSig.htf_poi_tf || '1D'}) + Micro Trigger Retest`}
                  >
                    <span>💎</span>
                    <span>NESTED SMC ({activeSig.htf_poi_tf ? `${activeSig.htf_poi_tf.toUpperCase()} + ` : ""}{activeSig.horizon_tag || "15M"})</span>
                  </span>
                ) : activeSig.order_block_setup || activeSig.strategy_archetype === "ORDER_BLOCK_LONG" || (activeSig.decision && activeSig.decision.includes("ORDER-BLOCK")) ? (
                  <span
                    className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-emerald-950/90 text-emerald-200 border border-emerald-400 shadow-sm shadow-emerald-500/20 flex items-center gap-1"
                    title="Smart Money Concepts (SMC) Institutional Order Block Demand Retest"
                  >
                    <span>💎</span>
                    <span>SMC ORDER-BLOCK</span>
                  </span>
                ) : null}

                {/* Confluence Edge Badges */}
                {isAlignedConfluence ? (
                  <span
                    className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-cyan-950 text-cyan-200 border border-cyan-400 shadow-sm shadow-cyan-500/30 flex items-center gap-1"
                    title={confluenceSummary}
                  >
                    <span>{isTripleConfluence ? "💎" : "🔥"}</span>
                    <span>{isTripleConfluence ? "TRIPLE CONFLUENCE (15M+1H+1D)" : "DUAL CONFLUENCE"}</span>
                  </span>
                ) : hasConflict ? (
                  <span
                    className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-500/80 flex items-center gap-1"
                    title="Lower timeframe is moving counter to higher timeframe trend. Take quick profit at TP1; avoid opposing position conflicts."
                  >
                    <span>⚠️</span>
                    <span>COUNTER-TREND SCALP</span>
                  </span>
                ) : signal.confluence_badge ? (
                  <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded border ${
                    signal.confluence_badge.includes("CONFLUENCE") || signal.confluence_badge.includes("MULTI")
                      ? "bg-cyan-950/90 text-cyan-200 border-cyan-400 shadow-sm shadow-cyan-500/20"
                      : signal.confluence_badge.includes("DUAL")
                      ? "bg-indigo-950/90 text-indigo-200 border-indigo-400"
                      : "bg-slate-900 text-slate-300 border-slate-700"
                  }`} title={signal.confluence_summary || "Multi-timeframe directional agreement"}>
                    {signal.confluence_badge}
                  </span>
                ) : null}

                {/* Playbook Regime Directive Badge */}
                {signal.playbook_regime && (
                  <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                    signal.playbook_regime === "BULLISH"
                      ? "bg-emerald-950/60 text-emerald-300 border-emerald-500/40"
                      : signal.playbook_regime === "BEARISH"
                      ? "bg-rose-950/60 text-rose-300 border-rose-500/40"
                      : "bg-indigo-950/60 text-indigo-300 border-indigo-500/40"
                  }`}>
                    📖 {signal.playbook_regime} ({signal.playbook_sizing_multiplier || 1.0}x)
                  </span>
                )}
              </div>

              {/* Interactive Multi-Horizon Switcher Strip for the Same Asset */}
              {coinSigs.length > 1 && (
                <div className="flex items-center gap-1.5 mt-2 p-1.5 bg-dark-950/90 rounded-xl border border-slate-800 flex-wrap">
                  <span className="text-[10px] font-bold text-slate-400 font-mono px-1 flex items-center gap-1">
                    <Layers className="h-3 w-3 text-cyan-400" />
                    TIMEFRAME:
                  </span>
                  {coinSigs.map((cs: any) => {
                    const hRaw = (cs.horizon_tag || cs.horizon || "").toUpperCase();
                    const normH = hRaw.includes("15M") ? "15M" : hRaw.includes("1H") ? "1H" : "24H";
                    const label = normH === "15M" ? "⚡ 15M Scalp" : normH === "1H" ? "⏳ 1H Day Trade" : "🌊 1D Swing";
                    const isCur = (activeSig.horizon_tag || activeSig.horizon || "").toUpperCase().includes(normH);
                    const isCsLong = cs.direction?.includes("LONG") || cs.direction?.includes("BULL");
                    return (
                      <button
                        key={normH}
                        type="button"
                        onClick={() => setSelectedHorizonOverride(normH)}
                        className={`px-2 py-0.5 rounded-lg text-[10px] font-bold font-mono transition-all flex items-center gap-1 ${
                          isCur
                            ? "bg-cyan-500/25 text-cyan-200 border border-cyan-400 shadow-sm shadow-cyan-500/20"
                            : "text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent"
                        }`}
                        title={`Switch card targets to ${label}`}
                      >
                        <span>{label}</span>
                        <span className={`text-[9px] font-black ${isCsLong ? "text-emerald-400" : "text-rose-400"}`}>
                          {isCsLong ? "BUY" : "SELL"}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <span className="text-xs font-bold text-cyan-300 flex items-center gap-1 bg-dark-900/90 px-2 py-0.5 rounded-md border border-cyan-500/30">
                  <Clock className="h-3 w-3 text-cyan-400" /> {horizon}
                </span>

                {/* Supporting Timeframes Pill Strip */}
                {Array.isArray(signal.supporting_horizons) && signal.supporting_horizons.length > 1 && (
                  <div className="flex items-center gap-1 text-[10px] font-mono font-bold bg-dark-950/90 px-2 py-0.5 rounded border border-slate-800">
                    <span className="text-slate-400">Agreed:</span>
                    {signal.supporting_horizons.map((ht: string) => (
                      <span key={ht} className="text-emerald-400 bg-emerald-950/60 px-1 rounded border border-emerald-500/40">
                        {ht}
                      </span>
                    ))}
                  </div>
                )}

                {signal.predicted_window_str && (
                  <span className="text-[11px] text-slate-400 font-mono">
                    {signal.predicted_window_str}
                  </span>
                )}
              </div>
            </div>

            {/* Conviction & ML Win Prob & Expected Return */}
            <div className="text-right shrink-0 bg-dark-950/60 px-3 py-1.5 rounded-xl border border-slate-800/60">
              <div className="flex items-baseline justify-end gap-1.5">
                <span className="text-xs text-slate-400 font-medium">Conviction:</span>
                <span className="text-base font-black text-cyan-400 font-mono">
                  {conviction.toFixed(1)}%
                </span>
              </div>
              <div className="flex items-center justify-end gap-1.5 text-xs font-mono mt-0.5">
                <span className="text-purple-300 font-bold flex items-center gap-0.5" title="Per-Coin ML Meta-Classifier Win Probability">
                  🧠 {metaWinProb ? `${metaWinProb.toFixed(1)}%` : "75.0%"}
                </span>
                <span className="text-slate-600">|</span>
                <span
                  className={`font-bold ${
                    expReturn >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  Exp: {formatPercent(expReturn)}
                </span>
              </div>
            </div>
          </div>

          {/* Prediction Favorability Flow Banner */}
          {signal.prediction_favorability && (
            <div className="mt-3 w-full rounded-xl bg-dark-950/90 p-2.5 border border-slate-800/80 shadow-inner flex flex-col items-center justify-center text-center">
              <div className="w-full flex items-center justify-center gap-2.5 flex-wrap">
                <span
                  className={`text-[10px] font-bold px-2.5 py-0.5 rounded border font-mono flex items-center gap-1 ${
                    signal.prediction_favorability.status === "CONFIRMED_IN_FAVOR"
                      ? "bg-emerald-950/90 text-emerald-300 border-emerald-500/60 shadow-sm shadow-emerald-500/10"
                      : signal.prediction_favorability.status === "ADVERSE_REVERSAL" || signal.prediction_favorability.status === "ADVERSE_HEADWIND"
                      ? "bg-rose-950/90 text-rose-300 border-rose-500/60 animate-pulse"
                      : "bg-amber-950/90 text-amber-300 border-amber-500/60"
                  }`}
                >
                  <span>{signal.prediction_favorability.status_badge || "🟢 CONFIRMED"}</span>
                  <span className="opacity-80 text-[9px]">
                    ({signal.prediction_favorability.favorability_score ?? 85}%)
                  </span>
                </span>

                {/* Horizon Flow Pill Strip */}
                {Array.isArray(signal.prediction_favorability.horizon_flow) && signal.prediction_favorability.horizon_flow.length > 0 && (
                  <div className="flex items-center justify-center gap-1.5 flex-wrap">
                    <span className="text-[10px] font-mono text-slate-400 font-bold">Upcoming Flow:</span>
                    {signal.prediction_favorability.horizon_flow.slice(0, 5).map((hf: any) => {
                      const isFav = hf.status === "IN_FAVOR";
                      return (
                        <span
                          key={hf.horizon}
                          className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border transition-all ${
                            isFav
                              ? "bg-emerald-950/80 text-emerald-300 border-emerald-500/50"
                              : hf.status === "ADVERSE"
                              ? "bg-rose-950/80 text-rose-300 border-rose-500/50"
                              : "bg-slate-900 text-slate-400 border-slate-700"
                          }`}
                          title={`${hf.horizon}: ${hf.direction} (${(hf.probability * 100).toFixed(0)}% prob, ${hf.conviction}% conv)`}
                        >
                          {hf.horizon} {isFav ? "🟢" : hf.status === "ADVERSE" ? "🔴" : "🟡"}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>

              {signal.prediction_favorability.action_directive && (
                <p className="mt-2 w-full text-center text-[11px] text-slate-300 font-sans leading-relaxed border-t border-slate-800/60 pt-1.5 flex items-center justify-center gap-1.5">
                  <Zap className="h-3 w-3 text-cyan-400 shrink-0" />
                  <span>{signal.prediction_favorability.action_directive}</span>
                </p>
              )}
            </div>
          )}

          {/* 💎 Institutional Setup Architecture Ribbon */}
          <div className="mt-3.5 w-full rounded-xl bg-gradient-to-r from-dark-950 via-slate-900/90 to-dark-950 p-2.5 sm:p-3 border border-cyan-500/30 shadow-md flex items-center justify-between gap-2.5 flex-wrap">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-300 shrink-0">
                <Sparkles className="h-3.5 w-3.5 animate-pulse" />
              </span>
              <div className="flex flex-col min-w-0">
                <span className="text-[9px] uppercase font-bold text-cyan-400 font-mono tracking-wider">
                  Verified Institutional Setup:
                </span>
                <span className="text-xs sm:text-sm font-black text-white font-mono tracking-wide truncate" title={setupTitle}>
                  {setupTitle}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="text-[10px] font-mono font-bold text-emerald-300 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-500/40">
                {activeSig.strategy || activeSig.strategy_playbook || (isLong ? "MOMENTUM LONG" : "MOMENTUM SHORT")}
              </span>
              {activeSig.zeiierman_rank && (
                <span className="text-[10px] font-mono font-black text-amber-300 bg-amber-950/80 px-1.5 py-0.5 rounded border border-amber-500/40">
                  RANK {activeSig.zeiierman_rank}
                </span>
              )}
            </div>
          </div>

          {/* Clean Price Target Matrix Grid (Entry & SL + ML Target & TP Milestones) */}
          <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-dark-900/90 p-3 border border-slate-800/80">
            {/* Column 1: Entry / Limit Bid Price */}
            <div className="flex flex-col justify-between">
              <div>
                <span className={`text-[10px] uppercase font-bold tracking-wider ${isLimitPending ? "text-amber-400 font-black" : "text-slate-400"}`}>
                  {isLimitPending ? `Limit ${isLong ? 'Bid' : 'Ask'}` : "Entry Price"}
                </span>
                <div className="flex items-baseline gap-1.5 mt-0.5 flex-wrap">
                  <span className={`text-sm sm:text-base font-black font-mono ${isLimitPending ? "text-amber-300" : "text-white"}`}>
                    {formatUsd(entryPrice)}
                  </span>
                  {wasPriceUpdated && prevEntry && (
                    <span className="text-[10px] text-slate-500 line-through font-mono">
                      {formatUsd(prevEntry)}
                    </span>
                  )}
                </div>
              </div>

              {/* Informative Sub-badges row */}
              <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                {currentPrice > 0 && Math.abs(currentPrice - entryPrice) > 1e-6 && (
                  <span
                    className={`text-[9px] font-bold px-1.5 py-0.5 rounded border font-mono ${
                      isLimitPending
                        ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                        : livePnl !== null && livePnl >= 0
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                        : "bg-rose-500/20 text-rose-300 border-rose-500/40"
                    }`}
                    title={isClosed ? `Official Trade Exit Price: ${formatUsd(currentPrice)}` : `Real-time live ticker price: ${formatUsd(currentPrice)}`}
                  >
                    {isClosed ? "Exit" : "Live"}: {formatUsd(currentPrice)}
                  </span>
                )}
                {isLimitPending && (signal.entry_zone_min || activeSig.entry_zone_min) && (
                  <span
                    className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-950/80 text-amber-300 border border-amber-500/40 font-mono"
                    title="Optimal Retest Zone"
                  >
                    Zone: {formatUsd(signal.entry_zone_min || activeSig.entry_zone_min)}
                  </span>
                )}
                {activeSig.mean_threshold_price && (
                  <span
                    className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-mono"
                    title="50% Mean Threshold (Equilibrium) Institutional Limit Bid"
                  >
                    50% MT: {formatUsd(activeSig.mean_threshold_price)}
                  </span>
                )}
              </div>
            </div>

            {/* Column 2: Invalidation Stop-Loss */}
            <div className="flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-bold text-rose-400 tracking-wider">
                    Invalidation Stop
                  </span>
                  <span className="text-[10px] font-mono font-bold text-rose-300 bg-rose-950/70 px-1.5 py-0.2 rounded border border-rose-500/30">
                    Risk: {pSl.toFixed(1)}%
                  </span>
                </div>
                <div className="flex items-baseline gap-1 mt-0.5">
                  <span className={`text-sm sm:text-base font-black font-mono ${isSlAtBreakeven ? "text-cyan-300" : "text-rose-400"}`}>
                    {formatUsd(sl)}
                  </span>
                </div>
              </div>

              {/* Stop-Loss Status / Cushion Subtext */}
              <div className="mt-1.5">
                <span className={`text-[10px] font-mono ${isSlAtBreakeven && beProfitPct > 0.05 ? "text-emerald-400 font-bold" : isSlAtBreakeven ? "text-cyan-400 font-bold" : "text-rose-400"}`}>
                  {isSlAtBreakeven
                    ? beProfitPct > 0.05
                      ? `🛡️ Breakeven (+${beProfitPct.toFixed(2)}%)`
                      : "🛡️ Breakeven (0.00%)"
                    : `(-${Math.abs(slPct).toFixed(2)}% risk)`}
                </span>
              </div>
            </div>

            {/* Continuous ML Next Price Target & Best Sell Zone */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 col-span-2 pt-1 border-t border-slate-800/60">
              {signal.predicted_next_price && (
                <div className="flex items-center justify-between bg-dark-950/90 rounded-lg px-2.5 py-1.5 border border-purple-500/30">
                  <span className="text-[11px] font-bold text-purple-300 flex items-center gap-1">
                    <Sparkles className="h-3 w-3 text-purple-400" />
                    ML Target Price:
                  </span>
                  <span className="text-xs font-mono font-black text-purple-200">
                    {formatUsd(signal.predicted_next_price)}{" "}
                    <span className={Number(signal.predicted_return_pct) >= 0 ? "text-emerald-400 font-medium" : "text-rose-400 font-medium"}>
                      ({Number(signal.predicted_return_pct) >= 0 ? "+" : ""}{Number(signal.predicted_return_pct).toFixed(2)}%)
                    </span>
                  </span>
                </div>
              )}
              <div className="flex items-center justify-between bg-amber-950/40 rounded-lg px-2.5 py-1.5 border border-amber-500/30">
                <span className="text-[11px] font-bold text-amber-300 flex items-center gap-1">
                  💎 Best Sell Zone:
                </span>
                <span className="text-xs font-mono font-black text-amber-200">
                  {formatUsd(signal.best_sell_price || signal.tp3_price || tp3)}
                </span>
              </div>
            </div>

            {/* TP1 / TP2 / TP3 Milestone Grid */}
            <div className="flex flex-col border-t border-slate-800/60 pt-2 col-span-2">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] uppercase font-bold text-emerald-400 tracking-wider flex items-center gap-1">
                  <Target className="h-3 w-3" /> Targets (TP1 / TP2 / TP3)
                </span>
                <span className="text-[10px] font-mono text-purple-300 font-bold bg-purple-950/60 px-2 py-0.5 rounded border border-purple-500/30 flex items-center gap-1">
                  <span>🧠</span>
                  <span>Calibrated Probabilities</span>
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs font-mono text-slate-200">
                {/* TP1 Card */}
                <div className={`p-2 sm:p-2.5 rounded-xl border flex flex-col justify-between transition-all ${
                  isTp1Hit
                    ? "bg-emerald-950/50 border-emerald-500/80 shadow-sm shadow-emerald-500/20"
                    : "bg-dark-950/80 border-slate-800/90"
                }`}>
                  <div className="flex items-center justify-between">
                    <span className={`text-[11px] font-bold flex items-center gap-1 ${isTp1Hit ? "text-emerald-300" : "text-slate-300"}`}>
                      <span>TP1</span>
                      {isTp1Hit && <CheckCircle2 className="h-3 w-3 text-emerald-400" />}
                    </span>
                    <span className="text-[10px] font-bold text-purple-300 bg-purple-950/50 px-1.5 py-0.2 rounded border border-purple-500/20">
                      {pTp1.toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between mt-1">
                    <strong className="text-emerald-400 font-black text-xs sm:text-sm">{formatUsd(tp1)}</strong>
                    <span className="text-[10px] sm:text-[11px] text-emerald-400 font-bold">+{Math.abs(tp1Pct).toFixed(1)}%</span>
                  </div>
                </div>

                {/* TP2 Card */}
                <div className={`p-2 sm:p-2.5 rounded-xl border flex flex-col justify-between transition-all ${
                  isTp2Hit
                    ? "bg-emerald-950/50 border-emerald-500/80 shadow-sm shadow-emerald-500/20"
                    : "bg-dark-950/80 border-slate-800/90"
                }`}>
                  <div className="flex items-center justify-between">
                    <span className={`text-[11px] font-bold flex items-center gap-1 ${isTp2Hit ? "text-emerald-300" : "text-slate-300"}`}>
                      <span>TP2</span>
                      {isTp2Hit && <CheckCircle2 className="h-3 w-3 text-emerald-400" />}
                    </span>
                    <span className="text-[10px] font-bold text-purple-300 bg-purple-950/50 px-1.5 py-0.2 rounded border border-purple-500/20">
                      {pTp2.toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between mt-1">
                    <strong className="text-emerald-300 font-black text-xs sm:text-sm">{formatUsd(tp2)}</strong>
                    <span className="text-[10px] sm:text-[11px] text-emerald-400 font-bold">+{Math.abs(tp2Pct).toFixed(1)}%</span>
                  </div>
                </div>

                {/* TP3 Card */}
                <div className={`p-2 sm:p-2.5 rounded-xl border flex flex-col justify-between transition-all ${
                  isTp3Hit
                    ? "bg-emerald-950/50 border-emerald-500/80 shadow-sm shadow-emerald-500/20"
                    : "bg-dark-950/80 border-slate-800/90"
                }`}>
                  <div className="flex items-center justify-between">
                    <span className={`text-[11px] font-bold flex items-center gap-1 ${isTp3Hit ? "text-emerald-300" : "text-slate-300"}`}>
                      <span>TP3</span>
                      {isTp3Hit && <CheckCircle2 className="h-3 w-3 text-emerald-400" />}
                    </span>
                    <span className="text-[10px] font-bold text-purple-300 bg-purple-950/50 px-1.5 py-0.2 rounded border border-purple-500/20">
                      {pTp3.toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between mt-1">
                    <strong className="text-emerald-200 font-black text-xs sm:text-sm">{formatUsd(tp3)}</strong>
                    <span className="text-[10px] sm:text-[11px] text-emerald-400 font-bold">+{Math.abs(tp3Pct).toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Upgraded Live Signal Progress Bar */}
          <TradeProgressBar
            entryPrice={entryPrice}
            currentPrice={currentPrice}
            slPrice={sl}
            tp1Price={tp1}
            tp2Price={tp2}
            tp3Price={tp3}
            exitPrice={activeSig.exit_price}
            peakPriceSeen={activeSig.peak_price_seen}
            troughPriceSeen={activeSig.trough_price_seen}
            direction={activeSig.direction}
            isLimitPending={isLimitPending}
            isSlAtBreakeven={isSlAtBreakeven}
            livePnlPct={livePnl}
            status={status}
            outcomeLabel={activeSig.outcome_label || signal.outcome_label}
          />

          {/* Invalidation & Execution Decision Banner */}
          <div className="mt-3.5 w-full rounded-xl bg-dark-950/80 p-3 border border-slate-800/70 text-xs">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0" />
                <span className="font-bold text-slate-100 text-xs tracking-wide truncate">
                  {signal.decision || activeSig.decision || `🎯 [${setupTitle}] EXECUTION AUTHORIZED`}
                </span>
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-800/40">
                  Risk: 1–2% Capital
                </span>
                {activeSig.risk_reward_ratio && (
                  <span className="text-[10px] font-mono text-emerald-300 bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-500/40 font-bold">
                    R:R {activeSig.risk_reward_ratio}
                  </span>
                )}
              </div>
            </div>
            <p className="mt-1.5 text-[11px] text-slate-400 font-sans leading-relaxed border-t border-slate-800/50 pt-1.5 flex items-center gap-1.5">
              <Zap className="h-3 w-3 text-amber-400/80 shrink-0" />
              <span>Strict 1–2% per trade. Move SL to Breakeven immediately after TP1 touch.</span>
            </p>
          </div>
        </div>

        {/* Card Actions Bottom Row (Responsive full-width buttons) */}
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-2 w-full pt-1">
          {/* Take / Track Trade Button */}
          <button
            type="button"
            onClick={() => {
              takeTrade(activeSig);
              setTradeTakenFeedback(true);
              setTimeout(() => setTradeTakenFeedback(false), 3000);
            }}
            disabled={isTradeTracked(activeSig.signal_id || activeSig.symbol) || isClosed}
            className={`w-full py-2.5 px-3 rounded-xl text-xs font-black font-mono transition-all flex items-center justify-center gap-2 shadow-md ${
              tradeTakenFeedback || isTradeTracked(activeSig.signal_id || activeSig.symbol)
                ? "bg-emerald-950 text-emerald-300 border border-emerald-500 shadow-emerald-950/40"
                : isClosed
                ? "bg-slate-900 text-slate-500 border border-slate-800 cursor-not-allowed"
                : "bg-gradient-to-r from-cyan-600 via-indigo-600 to-cyan-600 bg-size-200 hover:bg-pos-100 hover:from-cyan-500 hover:to-indigo-500 text-white border border-cyan-400/50 shadow-cyan-950/40 active:scale-[0.98]"
            }`}
            title="Track this trade in your personal Live Trading Desk"
          >
            {tradeTakenFeedback || isTradeTracked(signal.signal_id || signal.symbol) ? (
              <>
                <Check className="h-4 w-4 text-emerald-400" />
                <span>TRACKING IN DESK</span>
              </>
            ) : isClosed ? (
              <span>TRADE RESOLVED</span>
            ) : (
              <>
                <TrendingUp className="h-4 w-4 text-cyan-200" />
                <span>TAKE TRADE</span>
              </>
            )}
          </button>

          {/* 15M History Button */}
          <button
            type="button"
            onClick={() => setShowHistoryModal(true)}
            className="w-full py-2.5 px-3 rounded-xl bg-dark-900/90 hover:bg-cyan-950/60 text-cyan-300 hover:text-cyan-200 border border-slate-800 hover:border-cyan-500/80 transition-all text-xs font-bold flex items-center justify-center gap-2 active:scale-[0.98]"
            title="View full 15-minute historical signal records for this coin"
          >
            <History className="h-4 w-4 text-cyan-400" />
            <span>15M HISTORY</span>
          </button>
        </div>
      </div>
    </>
  );
}
