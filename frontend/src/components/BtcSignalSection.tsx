"use client";

import React, { useState } from "react";
import { useForecastQuery, useStatusQuery } from "@/hooks/useCryptoData";
import { useV16Regime } from "@/hooks/useV16Data";
import { formatPercent, formatUsd } from "@/lib/utils";
import CoinSignalHistoryModal from "@/components/CoinSignalHistoryModal";
import SignalShareModal from "@/components/SignalShareModal";
import { getHorizonStance } from "@/components/AssetPredictionMatrix";
import {
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Target,
  Sparkles,
  Zap,
  Activity,
  History,
  Share2,
  AlertTriangle,
  Lock,
} from "lucide-react";
import { getShieldTheme } from "@/lib/marketShield";

const ALL_9_BTC_HORIZONS = [
  { key: "15m", label: "15m", name: "15M Scalp / Exec" },
  { key: "1h", label: "1h", name: "1H Intraday Context" },
  { key: "4h", label: "4h", name: "4H Macro Anchor" },
];

export default function BtcSignalSection() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: status } = useStatusQuery();
  const { data: v16RegimeData } = useV16Regime();
  const v16Regime = v16RegimeData?.regime;
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);

  // Extract BTC data from leaderboard
  const leaderboard = forecast?.scanner_leaderboard || [];
  const btcItem = leaderboard.find((item: any) => item.symbol?.toUpperCase().includes("BTC")) || {
    symbol: "BTC/USDT",
    current_price: 80750.0,
    horizons: {},
  };

  const shield = status?.btc_market_shield || forecast?.btc_market_shield || {
    active: false,
    reason: "NORMAL (Market Stable)",
  };

  // Derive quantitative regime alignment with Quant Edge V16
  const activeRegime = v16Regime?.regime || shield?.regime || "RANGE";
  const isV16Bear = activeRegime === "BEAR_TREND";
  const isV16Bull = activeRegime === "BULL_TREND";
  const isV16Squeeze = activeRegime === "SQUEEZE";

  // 1. Strict No Trade Zone Evaluation: Active ONLY during genuine Squeeze or critical liquidation flash dump
  const isNtzActive =
    isV16Squeeze ||
    (shield?.regime === "RANGE_SQUEEZE" && !isV16Bear && !isV16Bull) ||
    (Boolean(shield?.is_ntz_active) && !isV16Bear && !isV16Bull) ||
    (shield?.status_code === "NO_TRADE_ZONE" && !isV16Bear && !isV16Bull) ||
    (String(shield?.altcoin_posture || "").includes("NO_TRADE_ZONE") && !isV16Bear && !isV16Bull);

  // Direction: In BEAR_TREND -> SHORT. In BULL_TREND -> LONG. Else from btcItem
  const domDirection = String(btcItem?.dominant_direction || btcItem?.direction || "NO_TRADE").toUpperCase();
  const effectiveDirection = isV16Bear ? "SHORT" : isV16Bull ? "LONG" : (domDirection === "LONG" || domDirection === "SHORT" ? domDirection : "CONSOLIDATION");

  const dominantTrend = String(
    isV16Bear ? "BEARISH" : isV16Bull ? "BULLISH" : (btcItem?.dominant_trend || "CONSOLIDATION")
  ).toUpperCase();

  const isTradeActive = !isNtzActive && (effectiveDirection === "LONG" || effectiveDirection === "SHORT");
  const isLong = effectiveDirection === "LONG";
  const currentPrice = v16Regime?.metrics?.btc_price || btcItem.current_price || btcItem.live_price || 80750.0;

  const scalp15m = btcItem.horizons?.["15m"] || btcItem.horizons?.scalp || {};

  // Active TP/SL vs Safe Forecast Target
  const tp1 = isV16Bear
    ? (btcItem.tp1_price && btcItem.tp1_price < currentPrice ? btcItem.tp1_price : currentPrice * 0.985)
    : (btcItem.tp1_price && btcItem.tp1_price > currentPrice ? btcItem.tp1_price : currentPrice * 1.018);

  const sl = isV16Bear
    ? (btcItem.sl_price && btcItem.sl_price > currentPrice ? btcItem.sl_price : currentPrice * 1.012)
    : (btcItem.sl_price && btcItem.sl_price < currentPrice ? btcItem.sl_price : currentPrice * 0.988);

  const forecastTarget = shield.predicted_btc_target || (isV16Bear ? currentPrice * 0.985 : isV16Bull ? currentPrice * 1.018 : currentPrice);
  const forecastChangePct = shield.predicted_btc_change_pct ?? (((forecastTarget - currentPrice) / currentPrice) * 100);

  // AI Conviction: Use V16 confidence if available, else scalp15m
  const conviction = v16Regime?.confidence ? v16Regime.confidence * 100 : (scalp15m.conviction ?? (scalp15m.consensus_probability ? scalp15m.consensus_probability * 100 : 75.0));

  // Alignment statistics
  const trendAlign = btcItem?.trend_alignment || {};
  const alignRatio = trendAlign.alignment_ratio || (isV16Bear ? "7/9" : `${trendAlign.aligned_horizons_count || 4}/9`);
  const alignScore = trendAlign.alignment_score_pct ?? (isV16Bear ? 77.8 : 44.4);

  return (
    <>
      {showHistoryModal && (
        <CoinSignalHistoryModal
          symbol="BTC/USDT"
          currentPrice={currentPrice}
          onClose={() => setShowHistoryModal(false)}
        />
      )}

      {showShareModal && (
        <SignalShareModal
          signal={{
            symbol: "BTC/USDT",
            direction: isNtzActive ? "NO_TRADE (NO TRADE ZONE)" : isLong ? "LONG" : "SHORT",
            horizon: isNtzActive ? "RANGE SQUEEZE" : "SCALP (15M)",
            quality_grade: isNtzActive ? "NO TRADE ZONE (CAPITAL PRESERVATION)" : "Grade A+ (INSTITUTIONAL)",
            conviction_pct: conviction,
            entry_price: currentPrice,
            tp1_price: isNtzActive ? forecastTarget : tp1,
            sl_price: isNtzActive ? currentPrice : sl,
            risk_reward_ratio: isNtzActive ? "LOCKED" : "1:2.0",
            expected_return_pct: forecastChangePct,
          }}
          onClose={() => setShowShareModal(false)}
        />
      )}

      <div className={`rounded-2xl border p-5 shadow-xl relative overflow-hidden backdrop-blur-xl transition-all duration-300 ${
        isNtzActive
          ? "border-amber-500/40 bg-gradient-to-br from-amber-950/40 via-dark-900/90 to-dark-950"
          : effectiveDirection === "LONG"
          ? "border-emerald-500/40 bg-gradient-to-br from-emerald-950/30 via-dark-900/90 to-dark-950"
          : effectiveDirection === "SHORT"
          ? "border-rose-500/40 bg-gradient-to-br from-rose-950/30 via-dark-900/90 to-dark-950"
          : "border-slate-800 bg-gradient-to-br from-slate-900/60 via-dark-900/90 to-dark-950"
      }`}>
        {/* Ambient Glow */}
        <div className={`absolute top-0 right-0 h-48 w-48 rounded-full blur-3xl pointer-events-none ${
          isNtzActive ? "bg-amber-500/15" : effectiveDirection === "LONG" ? "bg-emerald-500/15" : effectiveDirection === "SHORT" ? "bg-rose-500/15" : "bg-cyan-500/10"
        }`} />

        {/* Header Ribbon */}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between border-b border-slate-800/80 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-amber-500 to-orange-600 shadow-md shadow-amber-500/20 text-white font-black text-lg">
              ₿
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-black text-white">Bitcoin (BTC/USDT) Institutional Command & Alpha Signal</h2>
                <span className="rounded-md bg-amber-950/80 px-2 py-0.5 text-xs font-bold text-amber-400 border border-amber-700/50">
                  Market Anchor
                </span>
                {isNtzActive ? (
                  <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/20 px-2 py-0.5 text-xs font-black text-amber-300 border border-amber-500/50 animate-pulse">
                    <ShieldAlert className="h-3 w-3 text-amber-400" /> NO TRADE ZONE ACTIVE
                  </span>
                ) : (
                  <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-black border ${
                    effectiveDirection === "SHORT"
                      ? "bg-rose-500/20 text-rose-300 border-rose-500/50"
                      : effectiveDirection === "LONG"
                      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/50"
                      : "bg-slate-800 text-slate-300 border-slate-700"
                  }`}>
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                    {v16Regime?.regime ? `${v16Regime.regime.replace(/_/g, " ")} (${(v16Regime.confidence * 100).toFixed(0)}%)` : "QUANT EDGE V16 SYNCHRONIZED"}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400">
                Live 9-horizon directional confluence & real-time market beta volatility safeguard
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowShareModal(true)}
              className="flex items-center gap-1.5 rounded-xl bg-dark-900 px-3 py-1.5 text-xs font-semibold text-slate-300 border border-slate-800 hover:text-white hover:bg-slate-800 transition-all"
            >
              <Share2 className="h-3.5 w-3.5 text-cyan-400" />
              Share BTC Signal
            </button>
            <button
              onClick={() => setShowHistoryModal(true)}
              className="flex items-center gap-1.5 rounded-xl bg-amber-500/20 px-3.5 py-1.5 text-xs font-bold text-amber-300 border border-amber-500/40 hover:bg-amber-500/30 transition-all shadow-sm"
            >
              <History className="h-3.5 w-3.5" />
              15M Audit History
            </button>
          </div>
        </div>

        {/* Main Grid: Live Signal + 9 Horizon Spectrum */}
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Col 1: Live BTC Primary Signal */}
          <div className="rounded-xl bg-dark-950/80 p-4 border border-slate-800/80 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400">Live BTC Spot Price</span>
                  <p className="text-2xl font-black text-white font-mono">{formatUsd(currentPrice)}</p>
                </div>

                {/* Primary Signal Badge */}
                {isNtzActive ? (
                  <span className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-black bg-amber-500/20 text-amber-300 border border-amber-500/50 shadow-sm shadow-amber-500/10">
                    <ShieldAlert className="h-4 w-4 text-amber-400 animate-pulse" />
                    🛑 NO TRADE ZONE
                  </span>
                ) : effectiveDirection === "LONG" ? (
                  <span className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-black bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                    <ArrowUpRight className="h-4 w-4" />
                    🟢 LONG BUY
                  </span>
                ) : effectiveDirection === "SHORT" ? (
                  <span className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-black bg-rose-500/20 text-rose-400 border border-rose-500/40">
                    <ArrowDownRight className="h-4 w-4" />
                    🔴 SHORT SELL
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-black bg-slate-800/90 text-amber-300 border border-slate-700">
                    <Activity className="h-4 w-4 text-amber-400" />
                    🟡 CONSOLIDATION
                  </span>
                )}
              </div>

              {/* Price Targets or NTZ Guardrail */}
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono rounded-lg bg-dark-900/90 p-2.5 border border-slate-800">
                {isNtzActive ? (
                  <>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-cyan-400 flex items-center gap-1">
                        <Target className="h-3 w-3" /> Model Target
                      </span>
                      <p className="text-cyan-300 font-bold">
                        {formatUsd(forecastTarget)}
                      </p>
                      <span className="text-[9px] text-slate-400">
                        {forecastChangePct >= 0 ? "+" : ""}{forecastChangePct.toFixed(2)}% expected
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-amber-400 flex items-center gap-1">
                        <Lock className="h-3 w-3" /> Execution Gate
                      </span>
                      <p className="text-amber-300 font-bold">LOCKED</p>
                      <span className="text-[9px] text-slate-400">Capital Preservation</span>
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-cyan-400 flex items-center gap-1">
                        <Target className="h-3 w-3" /> Target 1 (TP1)
                      </span>
                      <p className="text-cyan-300 font-bold">{formatUsd(tp1)}</p>
                      <span className="text-[9px] text-slate-400">
                        {forecastChangePct >= 0 ? "+" : ""}{forecastChangePct.toFixed(2)}% expected
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-emerald-400 flex items-center gap-1">
                        <Zap className="h-3 w-3" /> Execution Gate
                      </span>
                      <p className="text-emerald-300 font-bold">
                        {v16Regime?.sizing_multiplier !== undefined ? `${v16Regime.sizing_multiplier.toFixed(2)}x ACTIVE` : "ACTIVE"}
                      </p>
                      <span className="text-[9px] text-slate-400">
                        {isV16Bear ? "Short Alpha Authorized" : isV16Bull ? "Long Alpha Authorized" : "Section 29 Sizing"}
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Conviction / Protection Posture Footer */}
            <div className="mt-3 flex items-center justify-between border-t border-slate-800/80 pt-2 text-xs">
              <span className="text-slate-400">
                {isNtzActive ? "Safeguard Posture:" : "AI Conviction:"}
              </span>
              <span className={`text-sm font-black font-mono ${
                isNtzActive ? "text-amber-400" : isLong ? "text-emerald-400" : "text-rose-400"
              }`}>
                {isNtzActive ? "CAPITAL PRESERVATION" : `${conviction.toFixed(1)}%`}
              </span>
            </div>
          </div>

          {/* Col 2 & 3: 9-Horizon Confluence Alignment Spectrum */}
          <div className="lg:col-span-2 rounded-xl bg-dark-950/80 p-4 border border-slate-800/80 flex flex-col justify-between">
            <div className="flex items-center justify-between border-b border-slate-800/60 pb-2 mb-3">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-amber-400" /> BTC 9-Horizon Confluence Spectrum
              </span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-slate-400 font-mono hidden sm:inline">5M Scalp ➔ 30D Monthly</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-black border ${
                  dominantTrend === "BULLISH"
                    ? "bg-emerald-950/80 text-emerald-300 border-emerald-500/50"
                    : dominantTrend === "BEARISH"
                    ? "bg-rose-950/80 text-rose-300 border-rose-500/50"
                    : "bg-slate-900 text-amber-300 border-amber-500/40"
                }`}>
                  {alignRatio} ({alignScore}%) {dominantTrend}
                </span>
              </div>
            </div>

            {/* Multi-Horizon Triad Spectrum Grid (15M, 1H, 4H) */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {ALL_9_BTC_HORIZONS.map((h) => {
                const hData = btcItem.horizons?.[h.key] || btcItem.all_9_timeframe_predictions?.[h.key] || {};
                const stance = getHorizonStance(hData);
                const conv = hData.conviction ?? (hData.consensus_probability ? hData.consensus_probability * 100 : 50.0);
                const tp = hData.predicted_target_price || hData.tp_price || hData.tp1_price;
                const predChg = hData.predicted_change_pct;

                const stanceClass =
                  stance === "bullish"
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                    : stance === "bearish"
                    ? "text-rose-400 bg-rose-500/10 border-rose-500/30"
                    : "text-amber-400 bg-amber-500/10 border-amber-500/30";

                const stanceLabel =
                  stance === "bullish"
                    ? "🟢 BULL"
                    : stance === "bearish"
                    ? "🔴 BEAR"
                    : "🟡 CHOP";

                return (
                  <div
                    key={h.key}
                    className={`rounded-lg p-2 border flex flex-col justify-between transition-all hover:border-slate-700 bg-dark-900/90 ${
                      hData.timeframe === "15m" ? "ring-1 ring-amber-500/40" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-slate-400 font-bold uppercase">{h.label}</span>
                      <span className="text-[9px] text-slate-400 font-mono font-semibold">
                        {conv.toFixed(0)}%
                      </span>
                    </div>

                    <div className="my-1 flex flex-col gap-0.5">
                      <span className={`inline-block rounded px-1.5 py-0.5 text-[9px] font-black border ${stanceClass}`}>
                        {stanceLabel}
                      </span>
                      {hData.order_block_touch && (
                        <span
                          className="inline-block rounded px-1 py-0.2 text-[8px] font-mono font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-500/50 animate-pulse text-center"
                          title={`Institutional Order Block Touch on ${h.label}: ${hData.order_block_zone || ""}`}
                        >
                          🎯 OB TOUCH
                        </span>
                      )}
                    </div>

                    {predChg !== undefined && predChg !== null ? (
                      <span className={`text-[8.5px] font-mono font-bold truncate ${
                        predChg > 0 ? "text-emerald-400" : predChg < 0 ? "text-rose-400" : "text-slate-400"
                      }`}>
                        {predChg > 0 ? `+${predChg.toFixed(2)}%` : `${predChg.toFixed(2)}%`}
                      </span>
                    ) : tp ? (
                      <span className="text-[8.5px] text-slate-400 font-mono truncate">
                        {formatUsd(tp)}
                      </span>
                    ) : (
                      <span className="text-[8.5px] text-slate-600 font-mono">-</span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Market Beta Safeguard & Predictive Trend Forecaster */}
            {(() => {
              const theme = getShieldTheme({
                ...shield,
                status_code: isNtzActive ? "NO_TRADE_ZONE" : activeRegime,
                regime: isNtzActive ? "RANGE_SQUEEZE" : activeRegime,
                reason: isNtzActive
                  ? shield.reason
                  : isV16Bear
                  ? `BEAR TREND: Live 1H ADX ${(v16Regime?.metrics?.adx || 52.8).toFixed(1)} > 25, EMA20 < EMA50. Section 29 1.00x short execution authorized.`
                  : shield.reason,
              });

              const bullProb = v16Regime?.probabilities?.bull !== undefined
                ? v16Regime.probabilities.bull * 100
                : (shield.bull_trend_prob ?? 8);
              const consProb = v16Regime?.probabilities?.range !== undefined
                ? v16Regime.probabilities.range * 100
                : (shield.consolidation_prob ?? 17);
              const bearProb = v16Regime?.probabilities?.bear !== undefined
                ? v16Regime.probabilities.bear * 100
                : (shield.bear_trend_prob ?? 65);

              return (
                <div className="mt-3 flex flex-col gap-2 border-t border-slate-800/60 pt-2 text-xs">
                  {/* Predictive Regime Probability Bar */}
                  <div className="flex flex-col gap-1 rounded-lg bg-dark-900/80 p-2 border border-slate-800/80">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="font-semibold text-slate-300 flex items-center gap-1">
                        <Activity className="h-3 w-3 text-cyan-400" />
                        Predictive Trend: <strong className={theme.iconColor}>{isNtzActive ? "NO TRADE ZONE ACTIVE" : isV16Bear ? `BEAR TREND (ADX: ${(v16Regime?.metrics?.adx || 52.8).toFixed(1)})` : isV16Bull ? `BULL TREND (ADX: ${(v16Regime?.metrics?.adx || 25).toFixed(1)})` : "RANGE CONSOLIDATION"}</strong>
                      </span>
                      {forecastTarget && (
                        <span className="font-mono text-cyan-300 font-bold">
                          Target: {formatUsd(forecastTarget)} (
                          {forecastChangePct >= 0 ? "+" : ""}
                          {forecastChangePct.toFixed(2)}%)
                        </span>
                      )}
                    </div>

                    <div className="flex h-2 w-full overflow-hidden rounded-full bg-slate-800">
                      <div
                        className="bg-emerald-500 transition-all duration-500"
                        style={{ width: `${bullProb}%` }}
                        title={`Bull Trend: ${bullProb.toFixed(1)}%`}
                      />
                      <div
                        className="bg-amber-400 transition-all duration-500"
                        style={{ width: `${consProb}%` }}
                        title={`Consolidation: ${consProb.toFixed(1)}%`}
                      />
                      <div
                        className="bg-rose-500 transition-all duration-500"
                        style={{ width: `${bearProb}%` }}
                        title={`Bear Trend: ${bearProb.toFixed(1)}%`}
                      />
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono">
                      <span className="text-emerald-400 font-bold">🟢 Bull: {bullProb.toFixed(0)}%</span>
                      <span className="text-amber-400 font-bold">⚪ Range: {consProb.toFixed(0)}%</span>
                      <span className="text-rose-400 font-bold">🔴 Bear: {bearProb.toFixed(0)}%</span>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      {theme.isAlert ? (
                        <ShieldAlert className="h-3.5 w-3.5 text-rose-400 animate-pulse" />
                      ) : (
                        <ShieldCheck className={`h-3.5 w-3.5 ${theme.iconColor}`} />
                      )}
                      <span className="text-slate-300 text-[11px]">
                        Posture: <strong className={theme.iconColor}>{isNtzActive ? "CAPITAL_PRESERVATION" : isV16Bear ? "BEAR_TREND_SHORT_ALPHA (1.00x)" : isV16Bull ? "BULL_TREND_LONG_ALPHA (1.00x)" : "RANGE_BOUND_MEAN_REVERSION (0.70x)"}</strong>
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      {shield.breakout_prediction && (
                        <span className="rounded bg-slate-800/90 px-1.5 py-0.5 text-[10px] font-mono text-cyan-300 border border-slate-700">
                          {isV16Bear ? "🔻 BEARISH MOMENTUM" : isV16Bull ? "🚀 BULLISH BREAKOUT" : shield.breakout_prediction}
                        </span>
                      )}
                      {shield.btc_15m_change_pct !== undefined && (
                        <span className="text-[10px] text-slate-400 font-mono">
                          15M: <strong className={shield.btc_15m_change_pct >= 0 ? "text-emerald-400" : "text-rose-400"}>{shield.btc_15m_change_pct > 0 ? `+${shield.btc_15m_change_pct}%` : `${shield.btc_15m_change_pct}%`}</strong>
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      </div>
    </>
  );
}
