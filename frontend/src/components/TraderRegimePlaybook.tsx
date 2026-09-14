"use client";

import React, { useState } from "react";
import { useForecastQuery, useStatusQuery } from "@/hooks/useCryptoData";
import { TraderPlaybook } from "@/lib/api";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Zap,
  Target,
  Scale,
  Lock,
  Sparkles,
  BookOpen
} from "lucide-react";

// Fallback Playbooks if backend sync is loading
const DEFAULT_PLAYBOOKS: Record<string, TraderPlaybook> = {
  BULLISH: {
    regime_type: "BULLISH",
    headline: "🟢 BULL MARKET REGIME: CONVEX UPSIDE CAPTURE & RUNNER ACCUMULATION",
    tactical_stance: "AGGRESSIVE_LONGS_AND_PULLBACK_BUYS",
    core_directive: "Ride the trend momentum, let winners run with trailing ratchet stops, and aggressively buy higher-low pullbacks to key dynamic moving averages.",
    sizing_multiplier: 1.15,
    recommended_leverage: "3x - 5x max (Avoid excessive leverage to survive liquidity wicks)",
    target_risk_reward: "1:2.5 to 1:4.0 (Expand TP targets for major runners)",
    stop_loss_policy: "Ratchet SL to Breakeven+ immediately once TP1 is hit. Never cut winners early.",
    preferred_setups: [
      {
        name: "Higher-Low EMA Pullback",
        desc: "Buy 15M/1H pullbacks testing 21 EMA or 50 EMA with oversold RSI bounce (35-45).",
        tag: "DIP_BUY"
      },
      {
        name: "Volatility Squeeze Breakout",
        desc: "Enter long on clean candle close above multi-hour resistance with volume expansion.",
        tag: "BREAKOUT"
      },
      {
        name: "High-Beta Relative Strength Long",
        desc: "Target altcoins outperforming BTC (RS_BTC > 0.3) that lead market upward surges.",
        tag: "ALPHA_LEADER"
      }
    ],
    dos: [
      "Buy dips at key dynamic moving average supports (21 EMA / 50 EMA / VWAP).",
      "Expand Take Profit targets and leave 25-40% runner positions for macro swing moves.",
      "Ratchet stop losses to breakeven once TP1 is reached to lock in a risk-free trade.",
      "Focus capital on top relative strength altcoins outperforming Bitcoin.",
      "Pyramid into winning trades on confirmed higher-low breakout retests."
    ],
    donts: [
      "DO NOT short strong upward momentum solely because RSI is 'overbought' (RSI stays high in bull runs).",
      "DO NOT take micro-scalp 0.5% profits prematurely while leaving massive 10%+ trends on the table.",
      "DO NOT panic sell spot positions on standard 3-5% intraday bull-market pullbacks.",
      "DO NOT chase vertical parabolic green candles with 10x+ leverage at resistance."
    ],
    checklist: [
      { rule: "Is the higher timeframe (4H/1D) trend aligned bullishly?", status: "REQUIRED" },
      { rule: "Is the trade entering at or near a pullback support (not extended >3 ATRs)?", status: "REQUIRED" },
      { rule: "Is Stop Loss placed strictly below swing low invalidation level?", status: "REQUIRED" },
      { rule: "Is the position size within 1.0x-1.25x risk tolerance?", status: "RECOMMENDED" },
      { rule: "Is trailing ratchet stop enabled for TP1 reach?", status: "REQUIRED" }
    ]
  },
  BEARISH: {
    regime_type: "BEARISH",
    headline: "🔴 BEAR MARKET REGIME: CAPITAL PRESERVATION & RELIEF FADE SHORTS",
    tactical_stance: "DEFENSIVE_CAPITAL_PRESERVATION_AND_SHORTS",
    core_directive: "Capital preservation is the absolute priority. Cash (USDT) is an active winning position. Suppress altcoin longs and fade overbought relief bounces into resistance.",
    sizing_multiplier: 0.50,
    recommended_leverage: "1x - 2x max (Strictly low leverage or spot cash allocation)",
    target_risk_reward: "1:1.5 to 1:2.0 (Take quick profits; do not overstay short targets)",
    stop_loss_policy: "Ultra-tight stop losses above resistance. Exit immediately upon invalidation.",
    preferred_setups: [
      {
        name: "Relief Rally Fade (Short)",
        desc: "Short oversold counter-trend bounces that test overhead 4H 50 EMA / resistance with RSI 55-65.",
        tag: "RALLY_FADE"
      },
      {
        name: "Breakdown Retest Short",
        desc: "Enter short when an established support level breaks down on volume and fails upon retest.",
        tag: "BREAKDOWN"
      },
      {
        name: "High-Negative Beta Hedge",
        desc: "Hedge spot portfolios with inverse perpetual shorts or high-beta bear sensitive assets.",
        tag: "INVERSE_HEDGE"
      }
    ],
    dos: [
      "Keep 50-80% of portfolio in USDT / stablecoins to maintain dry powder for generational bottoms.",
      "Automatically suppress or prune altcoin longs (altcoins drop 2x-3x harder than BTC).",
      "Fade overbought counter-trend relief rallies that stall into descending moving averages.",
      "Take profits quickly at TP1/TP2 because bear market bounces are fast and violent.",
      "Use strict, tight stop-losses and accept small losses immediately without emotional attachment."
    ],
    donts: [
      "DO NOT catch falling knives on plunging coins without multi-day volume absorption.",
      "DO NOT average down on losing long positions ('buying the dip' on a downtrend is fatal).",
      "DO NOT widen stop losses hoping for a rebound.",
      "DO NOT hold high-beta low-cap altcoins without stop-loss safeguards during systemic flushes."
    ],
    checklist: [
      { rule: "Are altcoin longs blocked or reduced to minimal exploratory size?", status: "REQUIRED" },
      { rule: "Is the short entry placed at overhead resistance / relief peak (not chasing the dump bottom)?", status: "REQUIRED" },
      { rule: "Is position sizing reduced to 0.4x-0.6x base capital?", status: "REQUIRED" },
      { rule: "Is TP target set conservatively with rapid partial take-profit enabled?", status: "REQUIRED" },
      { rule: "Is stop loss strictly anchored above the swing high?", status: "REQUIRED" }
    ]
  },
  CONSOLIDATION: {
    regime_type: "CONSOLIDATION",
    headline: "⚪ CONSOLIDATION REGIME: MEAN REVERSION & SQUEEZE BREAKOUT WATCH",
    tactical_stance: "RANGE_BOUND_MEAN_REVERSION_AND_SQUEEZE_COILING",
    core_directive: "Trade the range boundaries: buy support, sell resistance, take quick midline profits, and avoid breakout FOMO traps while monitoring impending squeeze expansion.",
    sizing_multiplier: 0.70,
    recommended_leverage: "2x - 3x max",
    target_risk_reward: "1:1.5 to 1:2.0 (Take 60-80% of profit at range midline / 20 SMA)",
    stop_loss_policy: "Strict stop loss just outside range boundary buffer (0.5 ATR beyond support/resistance).",
    preferred_setups: [
      {
        name: "Bollinger Band Mean Reversion",
        desc: "Buy lower BB touches with RSI < 35; sell/short upper BB touches with RSI > 65.",
        tag: "RANGE_BOUNCE"
      },
      {
        name: "Range Support Liquidity Sweep",
        desc: "Enter long when price sweeps below support low, rejects lower prices, and re-enters range.",
        tag: "LIQUIDITY_SWEEP"
      },
      {
        name: "Volatility Squeeze Trigger",
        desc: "Prepare orders for explosive expansion when Bollinger Band Width contracts below 1.5%.",
        tag: "SQUEEZE_WATCH"
      }
    ],
    dos: [
      "Buy at range support extremes and sell/short at range resistance extremes.",
      "Take 60-80% profits at the range midline (VWAP or 20 SMA) rather than hoping for massive runners.",
      "Monitor Choppiness Index (CHOP > 61.8) and Bollinger Band Width for squeeze contraction.",
      "Reduce trade frequency and wait patiently for prices to reach the perimeter of the range.",
      "Use time-based stops: close trades that stagnate at the midline to free up liquidity."
    ],
    donts: [
      "DO NOT buy green breakout candles at range highs (70%+ failure rate in choppy consolidation).",
      "DO NOT short red breakdown candles at range lows without multi-timeframe volume confirmation.",
      "DO NOT use oversized positions in sideways chop; chop generates death by papercuts from whipsaws.",
      "DO NOT trade inside the middle 50% of the range (no-man's land with 50/50 odds)."
    ],
    checklist: [
      { rule: "Is the entry located at the outer 20% perimeter of the trading range?", status: "REQUIRED" },
      { rule: "Is the position size scaled down to 0.6x-0.75x to mitigate whipsaw risk?", status: "REQUIRED" },
      { rule: "Is Take Profit 1 placed at the range midline (VWAP / 20 EMA)?", status: "REQUIRED" },
      { rule: "Is Stop Loss placed strictly beyond the range outer boundary?", status: "REQUIRED" },
      { rule: "Has breakout confirmation (volume + 4H candle close) occurred if attempting breakout?", status: "REQUIRED" }
    ]
  }
};

export default function TraderRegimePlaybookComponent() {
  const { data: forecast } = useForecastQuery();
  const { data: status } = useStatusQuery();

  const shield = status?.btc_market_shield || forecast?.btc_market_shield;
  const livePlaybook = shield?.trader_playbook || forecast?.trader_playbook;

  // Determine current active regime
  let activeRegimeKey = "CONSOLIDATION";
  if (shield?.predicted_trend === "BULLISH" || (shield?.bull_trend_prob && shield.bull_trend_prob >= 50)) {
    activeRegimeKey = "BULLISH";
  } else if (shield?.predicted_trend === "BEARISH" || (shield?.bear_trend_prob && shield.bear_trend_prob >= 50) || shield?.active) {
    activeRegimeKey = "BEARISH";
  }

  const [selectedTab, setSelectedTab] = useState<string>("LIVE");
  const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>({});

  const displayRegimeKey = selectedTab === "LIVE" ? activeRegimeKey : selectedTab;
  const currentPlaybook: TraderPlaybook = (selectedTab === "LIVE" && livePlaybook) ? livePlaybook : (DEFAULT_PLAYBOOKS[displayRegimeKey] || DEFAULT_PLAYBOOKS.CONSOLIDATION);

  const isBull = displayRegimeKey === "BULLISH";
  const isBear = displayRegimeKey === "BEARISH";

  const themeColors = isBull
    ? {
        border: "border-emerald-500/30",
        badgeBg: "bg-emerald-950/80 text-emerald-400 border-emerald-700/50",
        glow: "from-emerald-950/20 via-dark-900/90 to-teal-950/20",
        accent: "text-emerald-400",
        pill: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
        icon: TrendingUp,
      }
    : isBear
    ? {
        border: "border-rose-500/30",
        badgeBg: "bg-rose-950/80 text-rose-400 border-rose-700/50",
        glow: "from-rose-950/20 via-dark-900/90 to-amber-950/20",
        accent: "text-rose-400",
        pill: "bg-rose-500/20 text-rose-300 border-rose-500/30",
        icon: TrendingDown,
      }
    : {
        border: "border-indigo-500/30",
        badgeBg: "bg-indigo-950/80 text-indigo-300 border-indigo-700/50",
        glow: "from-indigo-950/20 via-dark-900/90 to-purple-950/20",
        accent: "text-indigo-400",
        pill: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
        icon: Activity,
      };

  const IconComponent = themeColors.icon;

  const toggleCheck = (idx: number) => {
    setCheckedItems(prev => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className={`rounded-2xl border ${themeColors.border} bg-gradient-to-br ${themeColors.glow} p-5 shadow-2xl relative overflow-hidden backdrop-blur-xl`}>
      {/* Header Bar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between border-b border-slate-800/80 pb-4">
        <div className="flex items-center gap-2.5 sm:gap-3">
          <div className="flex h-9 w-9 sm:h-10 sm:w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 shadow-md shadow-indigo-500/20 text-white font-black shrink-0">
            <BookOpen className="h-4 w-4 sm:h-5 sm:w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base sm:text-lg font-black text-white">Institutional Trader Regime Playbook</h2>
              <span className={`rounded-md px-2 py-0.5 text-xs font-bold border ${themeColors.badgeBg}`}>
                {selectedTab === "LIVE" ? "⚡ Live Synced" : "📖 Strategy Guide"}
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Gold-standard quantitative trade rules, position sizing, and tactical checklists adapted to current market mechanics
            </p>
          </div>
        </div>

        {/* Regime Tabs (Smooth touch scroll on mobile) */}
        <div className="flex items-center rounded-xl bg-dark-950/90 p-1 border border-slate-800 text-xs font-semibold overflow-x-auto touch-scroll no-scrollbar shrink-0 max-w-full">
          <button
            onClick={() => setSelectedTab("LIVE")}
            className={`whitespace-nowrap rounded-lg px-2.5 sm:px-3 py-1.5 transition-all flex items-center gap-1 ${
              selectedTab === "LIVE" ? "bg-cyan-500 text-dark-950 font-black shadow-sm" : "text-slate-400 hover:text-white"
            }`}
          >
            <Zap className="h-3 w-3" /> Live ({activeRegimeKey})
          </button>
          <button
            onClick={() => setSelectedTab("BULLISH")}
            className={`whitespace-nowrap rounded-lg px-2.5 sm:px-3 py-1.5 transition-all ${
              selectedTab === "BULLISH" ? "bg-emerald-500 text-dark-950 font-black shadow-sm" : "text-slate-400 hover:text-white"
            }`}
          >
            🟢 Bull
          </button>
          <button
            onClick={() => setSelectedTab("CONSOLIDATION")}
            className={`whitespace-nowrap rounded-lg px-2.5 sm:px-3 py-1.5 transition-all ${
              selectedTab === "CONSOLIDATION" ? "bg-indigo-500 text-white font-black shadow-sm" : "text-slate-400 hover:text-white"
            }`}
          >
            ⚪ Range
          </button>
          <button
            onClick={() => setSelectedTab("BEARISH")}
            className={`whitespace-nowrap rounded-lg px-2.5 sm:px-3 py-1.5 transition-all ${
              selectedTab === "BEARISH" ? "bg-rose-500 text-white font-black shadow-sm" : "text-slate-400 hover:text-white"
            }`}
          >
            🔴 Bear
          </button>
        </div>
      </div>

      {/* Core Directive Ribbon */}
      <div className="mt-4 rounded-xl bg-dark-950/90 p-3.5 border border-slate-800/80 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-800/80">
            <IconComponent className={`h-4 w-4 ${themeColors.accent}`} />
          </div>
          <div>
            <span className="text-[10px] uppercase font-mono font-bold text-slate-400 tracking-wider">
              Playbook Stance: {currentPlaybook.tactical_stance}
            </span>
            <h3 className="text-sm font-bold text-white leading-tight">{currentPlaybook.headline}</h3>
          </div>
        </div>
        <div className="text-xs text-slate-300 md:max-w-md italic border-t md:border-t-0 md:border-l border-slate-800/80 pt-2 md:pt-0 md:pl-3">
          &ldquo;{currentPlaybook.core_directive}&rdquo;
        </div>
      </div>

      {/* Grid: Tactical Directives (Sizing, Leverage, R:R, SL) */}
      <div className="mt-3 grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <div className="rounded-xl bg-dark-950/80 p-3 border border-slate-800/80 flex flex-col justify-between">
          <span className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1">
            <Scale className="h-3 w-3 text-cyan-400" /> Sizing Multiplier
          </span>
          <p className="mt-1 text-base font-black font-mono text-cyan-300">
            {currentPlaybook.sizing_multiplier.toFixed(2)}x Base Capital
          </p>
          <span className="text-[9px] text-slate-500 mt-0.5">
            {isBull ? "Expand size on pullbacks" : isBear ? "Defensive capital preservation" : "Scaled down for range chop"}
          </span>
        </div>

        <div className="rounded-xl bg-dark-950/80 p-3 border border-slate-800/80 flex flex-col justify-between">
          <span className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1">
            <Lock className="h-3 w-3 text-amber-400" /> Max Leverage
          </span>
          <p className="mt-1 text-base font-black font-mono text-amber-300">
            {currentPlaybook.recommended_leverage.split(" ")[0]}
          </p>
          <span className="text-[9px] text-slate-500 mt-0.5 truncate">
            {currentPlaybook.recommended_leverage}
          </span>
        </div>

        <div className="rounded-xl bg-dark-950/80 p-3 border border-slate-800/80 flex flex-col justify-between">
          <span className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1">
            <Target className="h-3 w-3 text-emerald-400" /> Target R:R Ratio
          </span>
          <p className="mt-1 text-base font-black font-mono text-emerald-300">
            {currentPlaybook.target_risk_reward.split(" ")[0]}
          </p>
          <span className="text-[9px] text-slate-500 mt-0.5 truncate">
            {currentPlaybook.target_risk_reward}
          </span>
        </div>

        <div className="rounded-xl bg-dark-950/80 p-3 border border-slate-800/80 flex flex-col justify-between">
          <span className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1">
            <ShieldCheck className="h-3 w-3 text-purple-400" /> Stop-Loss Policy
          </span>
          <p className="mt-1 text-xs font-bold text-purple-200 line-clamp-2">
            {currentPlaybook.stop_loss_policy}
          </p>
        </div>
      </div>

      {/* Actionable Rules: DOs vs DONTs */}
      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {/* DOs */}
        <div className="rounded-xl bg-emerald-950/20 p-4 border border-emerald-500/20">
          <div className="flex items-center gap-2 border-b border-emerald-500/20 pb-2 mb-3">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            <h4 className="text-xs font-black uppercase tracking-wider text-emerald-300">
              Institutional Best Practices (What To Do)
            </h4>
          </div>
          <ul className="space-y-2 text-xs text-slate-300">
            {currentPlaybook.dos.map((item, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <span className="text-emerald-400 font-bold shrink-0 mt-0.5">✓</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* DONTs */}
        <div className="rounded-xl bg-rose-950/20 p-4 border border-rose-500/20">
          <div className="flex items-center gap-2 border-b border-rose-500/20 pb-2 mb-3">
            <XCircle className="h-4 w-4 text-rose-400" />
            <h4 className="text-xs font-black uppercase tracking-wider text-rose-300">
              Critical Pitfalls & Traps (What To Avoid)
            </h4>
          </div>
          <ul className="space-y-2 text-xs text-slate-300">
            {currentPlaybook.donts.map((item, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <span className="text-rose-400 font-bold shrink-0 mt-0.5">✗</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Preferred Setup Archetypes */}
      <div className="mt-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5 text-cyan-400" /> Preferred Setup Archetypes for this Regime
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
          {currentPlaybook.preferred_setups.map((setup, idx) => (
            <div
              key={idx}
              className="rounded-xl bg-dark-950/80 p-3 border border-slate-800/80 hover:border-slate-700 transition-all flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <h5 className="text-xs font-bold text-white">{setup.name}</h5>
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-mono font-bold text-cyan-300 border border-slate-700">
                    {setup.tag}
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 leading-relaxed">{setup.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Pre-Flight Trade Execution Checklist */}
      <div className="mt-4 rounded-xl bg-dark-950/90 p-4 border border-slate-800/80">
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-2 mb-3">
          <span className="text-xs font-black uppercase tracking-wider text-white flex items-center gap-1.5 font-mono">
            <ShieldCheck className="h-4 w-4 text-emerald-400" /> Pre-Flight Trade Execution Discipline Checklist
          </span>
          <span className="text-[10px] text-slate-400 font-mono">
            {Object.values(checkedItems).filter(Boolean).length} / {currentPlaybook.checklist.length} Verified
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-xs">
          {currentPlaybook.checklist.map((c, idx) => {
            const isChecked = !!checkedItems[idx];
            return (
              <button
                key={idx}
                onClick={() => toggleCheck(idx)}
                className={`flex items-start gap-2.5 rounded-lg p-2 text-left transition-all border ${
                  isChecked
                    ? "bg-emerald-950/30 border-emerald-500/40 text-emerald-200"
                    : "bg-dark-900/90 border-slate-800/80 text-slate-300 hover:border-slate-700"
                }`}
              >
                <div className={`mt-0.5 h-4 w-4 shrink-0 rounded border flex items-center justify-center ${
                  isChecked ? "bg-emerald-500 border-emerald-400 text-dark-950 font-black text-[10px]" : "border-slate-600 bg-dark-950"
                }`}>
                  {isChecked && "✓"}
                </div>
                <div className="flex flex-col">
                  <span className="text-[11px] font-medium leading-tight">{c.rule}</span>
                  <span className={`text-[9px] font-mono mt-0.5 ${c.status === "REQUIRED" ? "text-amber-400 font-bold" : "text-slate-500"}`}>
                    [{c.status}]
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
