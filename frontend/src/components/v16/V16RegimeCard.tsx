"use client";

import React, { useState } from "react";
import { V16RegimeResponse } from "@/types/v16";
import { getRegimeTheme, formatPrice } from "@/lib/utils/v16";
import {
  Activity,
  ShieldCheck,
  ShieldAlert,
  Gauge,
  CheckCircle2,
  AlertTriangle,
  Lock,
  Unlock,
  TrendingUp,
  TrendingDown,
  Waves,
  Zap,
  Info,
} from "lucide-react";

interface Props {
  regimeData: V16RegimeResponse | null | undefined;
  isLoading: boolean;
}

export default function V16RegimeCard({ regimeData, isLoading }: Props) {
  const [activeStrategyTab, setActiveStrategyTab] = useState<"allowed" | "restricted">("allowed");

  if (isLoading || !regimeData) {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-5 animate-pulse text-slate-500 font-mono text-xs flex items-center justify-center min-h-[360px]">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-400 animate-spin" />
          <span>Synchronizing 9-State Quantitative Regime Classifier (Section 28-29 Spec)...</span>
        </div>
      </div>
    );
  }

  const theme = getRegimeTheme(regimeData.regime);
  const eligible = regimeData.eligible_strategies || [];
  const restricted = regimeData.restricted_strategies || [];
  const metrics = regimeData.metrics || {};
  const probs = regimeData.probabilities || {
    bull: 0.2,
    bear: 0.2,
    range: 0.4,
    breakout: 0.1,
    squeeze: 0.1,
  };

  const isThrottled = regimeData.sizing_multiplier < 1.0;
  const throttlePercent = Math.round((1 - regimeData.sizing_multiplier) * 100);

  // Volatility badge color
  const getVolBadgeColor = (vol: string) => {
    const v = (vol || "").toUpperCase();
    if (v === "HIGH" || v === "EXTREME") return "text-rose-400 bg-rose-950/60 border-rose-500/40";
    if (v === "LOW") return "text-teal-400 bg-teal-950/60 border-teal-500/40";
    return "text-amber-300 bg-amber-950/60 border-amber-500/40";
  };

  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-5 shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col justify-between space-y-4">
      {/* Background soft ambient radial */}
      <div className="absolute -top-16 -right-16 w-56 h-56 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-16 -left-16 w-56 h-56 bg-cyan-500/5 rounded-full blur-3xl pointer-events-none" />

      {/* 1. Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3 relative z-10">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-indigo-950/60 border border-indigo-500/30 text-indigo-400 shadow-[0_0_12px_rgba(99,102,241,0.2)]">
            <Activity className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold tracking-wider text-white font-mono uppercase">
                Market Regime State
              </h2>
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono bg-cyan-950/60 text-cyan-300 border border-cyan-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                LIVE SYNCED
              </span>
            </div>
            <p className="text-[10px] text-slate-400 font-mono mt-0.5">
              Dynamic Multi-Timeframe Volatility & Trend Evaluation
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-slate-950/80 border border-slate-700 text-slate-300">
            Section 28-29 Spec
          </span>
          {regimeData.updated_at_utc && (
            <span className="text-[9px] font-mono text-slate-400">
              {regimeData.updated_at_utc}
            </span>
          )}
        </div>
      </div>

      {/* 2. Main Regime Banner & Confidence */}
      <div className="relative z-10 flex items-center justify-between flex-wrap gap-3 bg-slate-950/40 p-3 rounded-xl border border-slate-800/60">
        <div
          className={`inline-flex items-center gap-2.5 px-3.5 py-2 rounded-xl border backdrop-blur-md shadow-lg transition-all duration-300 ${theme.bg} ${theme.border}`}
        >
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
            <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${theme.dot}`} />
          </span>
          <span className={`font-mono font-black text-sm tracking-wider uppercase ${theme.text}`}>
            {theme.label}
          </span>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-400 text-[11px]">Confidence:</span>
            <span className="font-bold text-white px-2 py-0.5 rounded bg-slate-900 border border-slate-700/80 text-cyan-300">
              {(regimeData.confidence * 100).toFixed(0)}%
            </span>
          </div>

          <div className="hidden sm:flex items-center gap-1.5">
            <span className="text-slate-400 text-[11px]">Risk Posture:</span>
            <span
              className={`font-bold px-2 py-0.5 rounded border text-[10px] ${
                isThrottled
                  ? "bg-amber-950/50 border-amber-500/40 text-amber-300"
                  : "bg-emerald-950/50 border-emerald-500/40 text-emerald-300"
              }`}
            >
              {isThrottled ? `THROTTLED (-${throttlePercent}%)` : "FULL EXPOSURE"}
            </span>
          </div>
        </div>
      </div>

      {/* 3. Primary Quant Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 font-mono text-xs relative z-10">
        {/* Trend Strength */}
        <div className="bg-slate-950/60 p-3 rounded-xl border border-slate-800/80 hover:border-slate-700 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">
              Trend Strength
            </span>
            <Gauge className="w-3.5 h-3.5 text-cyan-400" />
          </div>
          <div className="text-base font-black text-white mt-1 flex items-baseline gap-1">
            <span>{(regimeData.trend_strength * 100).toFixed(0)}</span>
            <span className="text-[10px] text-slate-400 font-normal">/ 100</span>
          </div>
          <div className="w-full bg-slate-800 h-1.5 rounded-full mt-2 overflow-hidden">
            <div
              className="bg-gradient-to-r from-cyan-500 to-indigo-500 h-full rounded-full transition-all duration-500 shadow-[0_0_8px_rgba(6,182,212,0.8)]"
              style={{ width: `${Math.min(100, Math.max(5, regimeData.trend_strength * 100))}%` }}
            />
          </div>
          <div className="text-[9px] text-slate-400 mt-1.5 flex justify-between">
            <span>ADX (14):</span>
            <span className="text-slate-200 font-bold">
              {metrics.adx !== undefined ? metrics.adx.toFixed(1) : (regimeData.trend_strength * 50).toFixed(1)}
            </span>
          </div>
        </div>

        {/* Volatility State */}
        <div className="bg-slate-950/60 p-3 rounded-xl border border-slate-800/80 hover:border-slate-700 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">
              Volatility State
            </span>
            <Waves className="w-3.5 h-3.5 text-amber-400" />
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            <span
              className={`text-xs font-black px-2 py-0.5 rounded border uppercase ${getVolBadgeColor(
                regimeData.volatility_state
              )}`}
            >
              {regimeData.volatility_state}
            </span>
          </div>
          <div className="text-[10px] text-slate-400 mt-2 font-mono">
            Normalized ATR / BB
          </div>
          <div className="text-[9px] text-slate-400 mt-0.5 flex justify-between">
            <span>ATR %ile: <strong className="text-slate-200">{metrics.atr_percentile ?? 50}%</strong></span>
            <span>BBW: <strong className="text-slate-200">{metrics.bb_width_percentile ?? 50}%</strong></span>
          </div>
        </div>

        {/* Sizing Multiplier */}
        <div className="bg-slate-950/60 p-3 rounded-xl border border-slate-800/80 hover:border-slate-700 transition-colors col-span-2 sm:col-span-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">
              Sizing Multiplier
            </span>
            <Zap className="w-3.5 h-3.5 text-cyan-400" />
          </div>
          <div className="text-base font-black text-cyan-300 mt-1 flex items-baseline gap-1">
            <span>{regimeData.sizing_multiplier.toFixed(2)}x</span>
            <span className="text-[10px] text-slate-400 font-normal">Section 29</span>
          </div>
          <div className="mt-2">
            {isThrottled ? (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-400">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                Capital Throttle Active
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-400">
                <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                Full Allocation (1.00x)
              </span>
            )}
          </div>
          <div className="text-[9px] text-slate-400 mt-0.5 truncate" title={regimeData.capital_preservation_reason || "Section 29 Risk Envelope"}>
            {regimeData.capital_preservation_reason || "Section 29 Risk Modulation"}
          </div>
        </div>
      </div>

      {/* 4. Live Macro Indicators HUD (Binance 1h BTC Kline Derivation) */}
      {metrics && metrics.btc_price && (
        <div className="relative z-10 bg-slate-950/70 p-2.5 rounded-xl border border-slate-800/70 font-mono text-[10px]">
          <div className="text-[9px] text-slate-400 uppercase font-bold tracking-wider mb-1.5 flex items-center justify-between">
            <span className="flex items-center gap-1 text-slate-300">
              <Activity className="w-3 h-3 text-cyan-400" />
              Live Macro Technical Determinants (BTC/USDT 1H)
            </span>
            <span className="text-slate-400">Authority: Binance Live</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-slate-300">
            <div className="bg-slate-900/80 p-1.5 rounded border border-slate-800 flex flex-col justify-between">
              <span className="text-slate-400 text-[9px]">BTC Price</span>
              <span className="font-bold text-white text-[11px]">{formatPrice(metrics.btc_price)}</span>
              <span className="text-[8px] text-slate-400">
                {metrics.ema_fast && metrics.ema_slow
                  ? metrics.ema_fast >= metrics.ema_slow
                    ? "EMA20 > EMA50 (Bull)"
                    : "EMA20 < EMA50 (Bear)"
                  : "Trend Filter"}
              </span>
            </div>

            <div className="bg-slate-900/80 p-1.5 rounded border border-slate-800 flex flex-col justify-between">
              <span className="text-slate-400 text-[9px]">ADX (14)</span>
              <span className="font-bold text-cyan-300 text-[11px]">
                {metrics.adx?.toFixed(1) || "N/A"}
              </span>
              <span className="text-[8px] text-slate-400">
                {(metrics.adx || 0) >= 25 ? "Strong Trend Active" : "Weak / Consolidation"}
              </span>
            </div>

            <div className="bg-slate-900/80 p-1.5 rounded border border-slate-800 flex flex-col justify-between">
              <span className="text-slate-400 text-[9px]">RSI (14)</span>
              <span
                className={`font-bold text-[11px] ${
                  (metrics.rsi || 50) > 70
                    ? "text-rose-400"
                    : (metrics.rsi || 50) < 30
                    ? "text-teal-400"
                    : "text-amber-300"
                }`}
              >
                {metrics.rsi?.toFixed(1) || "N/A"}
              </span>
              <span className="text-[8px] text-slate-400">
                {(metrics.rsi || 50) > 52 ? "Bullish Momentum" : (metrics.rsi || 50) < 48 ? "Bearish Momentum" : "Neutral Corridor"}
              </span>
            </div>

            <div className="bg-slate-900/80 p-1.5 rounded border border-slate-800 flex flex-col justify-between">
              <span className="text-slate-400 text-[9px]">BB Width / ATR %</span>
              <span className="font-bold text-indigo-300 text-[11px]">
                {metrics.bb_width_percentile?.toFixed(0)}% / {metrics.atr_percentile?.toFixed(0)}%
              </span>
              <span className="text-[8px] text-slate-400">
                {(metrics.bb_width_percentile || 50) <= 20 ? "Volatility Squeeze" : "Standard Volatility"}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* 5. Probabilistic Regime Distribution Bar */}
      {probs && (
        <div className="relative z-10 space-y-1.5 font-mono text-[10px]">
          <div className="flex items-center justify-between text-slate-400 text-[9px]">
            <span className="uppercase font-bold tracking-wider">Regime Probability Distribution</span>
            <span>Sum: 100%</span>
          </div>
          <div className="h-2 rounded-full bg-slate-950 flex overflow-hidden border border-slate-800 shadow-inner">
            <div
              style={{ width: `${(probs.bull || 0) * 100}%` }}
              className="bg-emerald-500 transition-all duration-500"
              title={`Bull Trend: ${((probs.bull || 0) * 100).toFixed(0)}%`}
            />
            <div
              style={{ width: `${(probs.bear || 0) * 100}%` }}
              className="bg-rose-500 transition-all duration-500"
              title={`Bear Trend: ${((probs.bear || 0) * 100).toFixed(0)}%`}
            />
            <div
              style={{ width: `${(probs.range || 0) * 100}%` }}
              className="bg-indigo-500 transition-all duration-500"
              title={`Range: ${((probs.range || 0) * 100).toFixed(0)}%`}
            />
            <div
              style={{ width: `${(probs.breakout || 0) * 100}%` }}
              className="bg-purple-500 transition-all duration-500"
              title={`Breakout: ${((probs.breakout || 0) * 100).toFixed(0)}%`}
            />
            <div
              style={{ width: `${(probs.squeeze || 0) * 100}%` }}
              className="bg-cyan-500 transition-all duration-500"
              title={`Squeeze: ${((probs.squeeze || 0) * 100).toFixed(0)}%`}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between text-[9px] text-slate-400 pt-0.5 px-0.5">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              Bull {((probs.bull || 0) * 100).toFixed(0)}%
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
              Bear {((probs.bear || 0) * 100).toFixed(0)}%
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
              Range {((probs.range || 0) * 100).toFixed(0)}%
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
              Breakout {((probs.breakout || 0) * 100).toFixed(0)}%
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
              Squeeze {((probs.squeeze || 0) * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      )}

      {/* 6. Interactive Strategy Eligibility Filter Tabs */}
      <div className="pt-3 border-t border-slate-800/80 relative z-10">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-2.5">
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-[11px] font-mono text-slate-300 font-bold uppercase tracking-wider">
              Strategy Eligibility Filter
            </span>
          </div>

          {/* Interactive Tabs */}
          <div className="flex items-center p-0.5 rounded-lg bg-slate-950/80 border border-slate-800 font-mono text-[10px]">
            <button
              onClick={() => setActiveStrategyTab("allowed")}
              className={`px-2.5 py-1 rounded-md font-bold transition-all flex items-center gap-1.5 ${
                activeStrategyTab === "allowed"
                  ? "bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Unlock className="w-2.5 h-2.5" />
              <span>{eligible.length} Allowed</span>
            </button>
            <button
              onClick={() => setActiveStrategyTab("restricted")}
              className={`px-2.5 py-1 rounded-md font-bold transition-all flex items-center gap-1.5 ${
                activeStrategyTab === "restricted"
                  ? "bg-rose-950/80 text-rose-300 border border-rose-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Lock className="w-2.5 h-2.5" />
              <span>{restricted.length} Restricted</span>
            </button>
          </div>
        </div>

        {/* Tab Content */}
        {activeStrategyTab === "allowed" ? (
          <div>
            <div className="flex flex-wrap gap-1.5">
              {eligible.length > 0 ? (
                eligible.map((strat) => (
                  <span
                    key={strat}
                    className="inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2.5 py-1 rounded-lg bg-emerald-950/40 text-emerald-300 border border-emerald-500/30 hover:border-emerald-400/50 transition-colors shadow-sm"
                  >
                    <CheckCircle2 className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                    {strat.replace(/_/g, " ")}
                  </span>
                ))
              ) : (
                <span className="text-xs text-amber-400 font-mono flex items-center gap-1.5 p-2 rounded-lg bg-amber-950/30 border border-amber-500/30">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                  Market in protective freeze: No aggressive archetypes permitted under current volatility.
                </span>
              )}
            </div>
            <p className="text-[9px] font-mono text-slate-400 mt-2 flex items-center gap-1">
              <Info className="w-3 h-3 text-slate-400" />
              Authorized for generation with Section 29 risk multiplier:{" "}
              <strong className="text-cyan-300">{regimeData.sizing_multiplier.toFixed(2)}x</strong>
            </p>
          </div>
        ) : (
          <div>
            <div className="flex flex-wrap gap-1.5">
              {restricted.length > 0 ? (
                restricted.map((strat) => (
                  <span
                    key={strat}
                    className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold px-2.5 py-1 rounded-lg bg-rose-950/30 text-rose-300/80 border border-rose-500/20 hover:border-rose-400/40 transition-colors line-through decoration-rose-500/50"
                  >
                    <Lock className="w-2.5 h-2.5 text-rose-400 flex-shrink-0" />
                    {strat.replace(/_/g, " ")}
                  </span>
                ))
              ) : (
                <span className="text-xs text-slate-400 font-mono p-2 rounded-lg bg-slate-950/40 border border-slate-800">
                  No strategies actively restricted under current macro parameters.
                </span>
              )}
            </div>
            <div className="mt-2 p-2 rounded-lg bg-rose-950/20 border border-rose-500/20 flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-rose-400 mt-0.5 flex-shrink-0" />
              <p className="text-[9px] font-mono text-rose-300/90 leading-tight">
                <strong>Section 29 Protection Rule:</strong> Counter-trend and uncalibrated breakout archetypes are throttled to prevent false-breakout capital erosion while market is in{" "}
                <span className="font-bold text-white uppercase">{regimeData.regime}</span> regime.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
