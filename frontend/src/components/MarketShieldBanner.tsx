"use client";

import React from "react";
import { useStatusQuery, useForecastQuery } from "@/hooks/useCryptoData";
import {
  ShieldAlert,
  ShieldCheck,
  Zap,
  Activity,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Compass,
  Sparkles,
  Gauge,
  Layers,
} from "lucide-react";
import { getShieldTheme } from "@/lib/marketShield";

export default function MarketShieldBanner() {
  const { data: status } = useStatusQuery();
  const { data: forecast } = useForecastQuery();

  const shield = status?.btc_market_shield || forecast?.btc_market_shield || {
    active: false,
    status_code: "NORMAL",
    regime: "STABLE",
    regime_label: "MARKET STABLE",
    reason: "NORMAL (Market Stable)",
  };

  const theme = getShieldTheme(shield);
  const btcPrice = shield.btc_price;
  const btc15m = shield.btc_15m_change_pct;
  const btc1h = shield.btc_1h_change_pct;
  const btc24h = shield.btc_24h_change_pct;
  const rsi1h = shield.btc_rsi_1h;
  const trendStructure = shield.trend_structure;
  const compositeScore = shield.composite_score;
  const isSqueeze = shield.is_squeeze;
  const bbw15m = shield.bbw_15m_pct;

  // Predictive Trend & Price Projection Properties
  const predictedTrend = shield.predicted_trend || "CONSOLIDATION";
  const trendProb = shield.trend_probability ?? 60.0;
  const bullProb = shield.bull_trend_prob ?? 30.0;
  const bearProb = shield.bear_trend_prob ?? 20.0;
  const consProb = shield.consolidation_prob ?? 50.0;
  const predTarget = shield.predicted_btc_target;
  const predChangePct = shield.predicted_btc_change_pct ?? 0.0;
  const breakoutPred = shield.breakout_prediction || "⚖️ RANGE BOUND";
  const altcoinPosture = shield.altcoin_posture || "STANDARD_EXECUTION";

  // Visual container styling based on market regime
  const containerStyle = shield.active
    ? "border-rose-500/70 bg-gradient-to-r from-rose-950/50 via-dark-900/90 to-red-950/40 shadow-lg shadow-rose-500/15"
    : theme.label === "CAUTION"
    ? "border-amber-500/60 bg-gradient-to-r from-amber-950/40 via-dark-900/90 to-orange-950/20 shadow-lg shadow-amber-500/10"
    : theme.label === "BULLISH EXPANSION"
    ? "border-emerald-500/50 bg-gradient-to-r from-emerald-950/40 via-dark-900/90 to-teal-950/20 shadow-lg shadow-emerald-500/15"
    : theme.label === "DIP ACCUMULATION"
    ? "border-teal-500/50 bg-gradient-to-r from-teal-950/40 via-dark-900/90 to-emerald-950/20 shadow-lg shadow-teal-500/15"
    : theme.label === "BEARISH DRIFT"
    ? "border-orange-500/50 bg-gradient-to-r from-orange-950/40 via-dark-900/90 to-rose-950/20 shadow-lg shadow-orange-500/15"
    : theme.label === "RANGE CONSOLIDATION"
    ? "border-indigo-500/50 bg-gradient-to-r from-indigo-950/40 via-dark-900/90 to-slate-900/80 shadow-lg shadow-indigo-500/15"
    : "border-cyan-500/30 bg-gradient-to-r from-cyan-950/30 via-dark-900/90 to-indigo-950/20 shadow-lg shadow-cyan-500/5";

  return (
    <div className={`rounded-2xl border p-4 sm:p-5 transition-all relative overflow-hidden backdrop-blur-xl ${containerStyle}`}>
      {/* Background ambient glow */}
      <div className={`absolute -top-10 -right-10 h-36 w-36 rounded-full blur-3xl pointer-events-none ${theme.glowBg}`} />

      {/* Row 1: Header, Main Stance, Predictive Probability Radar & Target Projection */}
      <div className="flex flex-col gap-3.5 xl:flex-row xl:items-center xl:justify-between relative z-10">
        {/* Left Section: Icon & Main Status */}
        <div className="flex items-start sm:items-center gap-3.5">
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border shadow-inner ${
              theme.isAlert
                ? "border-rose-400/60 bg-rose-500/20 text-rose-300 shadow-rose-500/30 animate-pulse"
                : theme.label === "CAUTION"
                ? "border-amber-400/50 bg-amber-500/15 text-amber-300"
                : theme.label === "BULLISH EXPANSION"
                ? "border-emerald-400/50 bg-emerald-500/15 text-emerald-300 shadow-emerald-500/20"
                : theme.label === "BEARISH DRIFT"
                ? "border-orange-400/50 bg-orange-500/15 text-orange-300"
                : theme.label === "RANGE CONSOLIDATION"
                ? "border-indigo-400/50 bg-indigo-500/15 text-indigo-300 shadow-indigo-500/20"
                : "border-cyan-400/40 bg-cyan-500/10 text-cyan-300 shadow-cyan-500/20"
            }`}
          >
            {theme.isAlert ? (
              <ShieldAlert className="h-6 w-6 text-rose-400" />
            ) : theme.label === "CAUTION" ? (
              <AlertTriangle className="h-6 w-6 text-amber-400" />
            ) : theme.label === "BULLISH EXPANSION" ? (
              <TrendingUp className="h-6 w-6 text-emerald-400" />
            ) : theme.label === "BEARISH DRIFT" ? (
              <TrendingDown className="h-6 w-6 text-orange-400" />
            ) : theme.label === "RANGE CONSOLIDATION" ? (
              <Activity className="h-6 w-6 text-indigo-400" />
            ) : (
              <ShieldCheck className={`h-6 w-6 ${theme.iconColor}`} />
            )}
          </div>

          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5 font-mono">
                [SHIELD 🛡️] Market Beta:
              </span>
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-black uppercase tracking-wide border ${theme.badgeBg}`}>
                <span className="relative flex h-2 w-2">
                  <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${theme.pingColor}`}></span>
                  <span className={`relative inline-flex h-2 w-2 rounded-full ${theme.dotColor}`}></span>
                </span>
                {theme.regimeBadge}
              </span>
              <span className="text-xs font-semibold text-slate-300">
                {theme.statusTitle}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              {theme.subline}
            </p>
          </div>
        </div>

        {/* Predictive Trend Radar & Forecast Probabilities */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 bg-dark-950/80 p-2.5 rounded-xl border border-slate-800/90">
          <div className="flex flex-col gap-1 min-w-[200px]">
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-400 font-bold flex items-center gap-1">
                <Gauge className="h-3.5 w-3.5 text-cyan-400" />
                Forecast Radar:
              </span>
              <span className={`font-black ${predictedTrend === "BULLISH" ? "text-emerald-400" : predictedTrend === "BEARISH" ? "text-rose-400" : "text-indigo-300"}`}>
                {predictedTrend} ({trendProb}%)
              </span>
            </div>
            
            {/* 3-Way Probability Bar */}
            <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden flex">
              <div
                style={{ width: `${bullProb}%` }}
                className="bg-emerald-500 h-full transition-all duration-500"
                title={`Bullish Trend Probability: ${bullProb}%`}
              />
              <div
                style={{ width: `${consProb}%` }}
                className="bg-indigo-500 h-full transition-all duration-500"
                title={`Consolidation Probability: ${consProb}%`}
              />
              <div
                style={{ width: `${bearProb}%` }}
                className="bg-rose-500 h-full transition-all duration-500"
                title={`Bearish Breakdown Probability: ${bearProb}%`}
              />
            </div>

            <div className="flex items-center justify-between text-[9.5px] font-mono text-slate-400">
              <span className="text-emerald-400">🟢 Bull: {bullProb}%</span>
              <span className="text-indigo-300">⚪ Cons: {consProb}%</span>
              <span className="text-rose-400">🔴 Bear: {bearProb}%</span>
            </div>
          </div>

          {/* Predicted BTC Price Target */}
          {predTarget !== undefined && predTarget > 0 && (
            <div className="flex flex-col border-l sm:border-slate-800/80 sm:pl-3">
              <span className="text-[10px] text-purple-300 font-bold uppercase tracking-wider flex items-center gap-1">
                <Sparkles className="h-3 w-3 text-purple-400" />
                Predicted BTC Target
              </span>
              <span className="text-sm font-mono font-black text-white mt-0.5">
                ${predTarget.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}{" "}
                <span className={`text-[11px] font-bold ${predChangePct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  ({predChangePct >= 0 ? "+" : ""}{predChangePct}%)
                </span>
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Row 2: Live Metric Chips & Quantitative Safeguard Flags */}
      <div className="mt-3.5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800/60 pt-3 relative z-10 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          {btcPrice !== undefined && btcPrice > 0 && (
            <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">BTC:</span>
              <span className="font-bold text-white">
                ${btcPrice.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
              </span>
            </div>
          )}

          {btc15m !== undefined && (
            <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">15M:</span>
              <span className={`font-bold flex items-center ${btc15m >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {btc15m >= 0 ? <TrendingUp className="h-3 w-3 mr-0.5 inline" /> : <TrendingDown className="h-3 w-3 mr-0.5 inline" />}
                {btc15m > 0 ? `+${btc15m}%` : `${btc15m}%`}
              </span>
            </div>
          )}

          {btc1h !== undefined && (
            <div className="hidden sm:flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">1H:</span>
              <span className={`font-bold flex items-center ${btc1h >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {btc1h >= 0 ? <TrendingUp className="h-3 w-3 mr-0.5 inline" /> : <TrendingDown className="h-3 w-3 mr-0.5 inline" />}
                {btc1h > 0 ? `+${btc1h}%` : `${btc1h}%`}
              </span>
            </div>
          )}

          {btc24h !== undefined && (
            <div className="hidden md:flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">24H:</span>
              <span className={`font-bold flex items-center ${btc24h >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {btc24h >= 0 ? <TrendingUp className="h-3 w-3 mr-0.5 inline" /> : <TrendingDown className="h-3 w-3 mr-0.5 inline" />}
                {btc24h > 0 ? `+${btc24h}%` : `${btc24h}%`}
              </span>
            </div>
          )}

          {compositeScore !== undefined && (
            <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">Score:</span>
              <span className={`font-black ${compositeScore >= 20 ? "text-emerald-400" : compositeScore <= -20 ? "text-rose-400" : "text-cyan-300"}`}>
                {compositeScore > 0 ? `+${compositeScore}` : compositeScore}
              </span>
            </div>
          )}

          {rsi1h !== undefined && (
            <div className="hidden md:flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">RSI(1H):</span>
              <span className={`font-bold ${rsi1h >= 60 ? "text-emerald-400" : rsi1h <= 40 ? "text-rose-400" : "text-cyan-300"}`}>
                {rsi1h}
              </span>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Breakout Forecast Badge */}
          {breakoutPred && (
            <div className="flex items-center gap-1.5 rounded-lg border border-indigo-500/50 bg-indigo-950/60 px-2.5 py-1 text-[11px] text-indigo-300 font-mono">
              <Compass className="h-3.5 w-3.5 text-indigo-400" />
              <span>{breakoutPred}</span>
            </div>
          )}

          {/* Altcoin Posture Strategy Badge */}
          <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
            <Zap className="h-3.5 w-3.5 text-indigo-400" />
            <span>
              Altcoins:{" "}
              <strong className={shield.active ? "text-rose-400" : "text-emerald-400"}>
                {shield.active ? "🛡️ Longs Paused" : "🟢 Longs Allowed"}
              </strong>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
