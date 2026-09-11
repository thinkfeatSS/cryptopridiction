import { BtcMarketShield } from "./api";

export interface ShieldTheme {
  border: string;
  iconColor: string;
  dotColor: string;
  pingColor: string;
  isAlert: boolean;
  badgeBg: string;
  glowBg: string;
  headline: string;
  subline: string;
  label: string;
  regimeBadge: string;
  statusTitle: string;
}

export function getShieldTheme(shield?: BtcMarketShield): ShieldTheme {
  const code = (shield?.status_code || "").toUpperCase();
  const regime = (shield?.regime || "").toUpperCase();
  const isActive = Boolean(shield?.active);
  const reason = shield?.reason || "";

  // 1. ALERT_DUMP / SEVERE DUMP (Flash Crash / Full Risk-off)
  if (code === "ALERT_DUMP" || regime === "DUMP" || reason.toUpperCase().includes("SEVERE DUMP")) {
    return {
      border: "border-red-600/80 bg-red-950/70 text-red-200 shadow-red-600/30 animate-pulse",
      iconColor: "text-red-400",
      dotColor: "bg-red-500",
      pingColor: "bg-red-400",
      isAlert: true,
      badgeBg: "bg-red-500/20 text-red-200 border-red-500/60 shadow-sm shadow-red-500/20",
      glowBg: "bg-red-500/25",
      headline: "🚨 Severe Systemic Dump Detected",
      subline: "BTC systemic sell-off in progress. Emergency risk-off and capital preservation active across all assets.",
      label: "ALERT_DUMP",
      regimeBadge: "CRITICAL DUMP",
      statusTitle: reason || "SEVERE DUMP (High Volatility Flush)",
    };
  }

  // 2. DEFENSIVE (BTC Dump / Circuit Breaker Active)
  if (code === "DEFENSIVE" || regime === "DEFENSIVE" || isActive || reason.toUpperCase().includes("DEFENSIVE")) {
    return {
      border: "border-rose-500/70 bg-rose-950/60 text-rose-300 shadow-rose-500/20 animate-pulse",
      iconColor: "text-rose-400",
      dotColor: "bg-rose-500",
      pingColor: "bg-rose-400",
      isAlert: true,
      badgeBg: "bg-rose-500/20 text-rose-300 border-rose-500/50 shadow-sm shadow-rose-500/20",
      glowBg: "bg-rose-500/20",
      headline: "⚠️ BTC Market Beta Circuit Breaker Active",
      subline: "Altcoin Long executions temporarily paused to prevent correlated cascade stop-outs. Short setups active.",
      label: "DEFENSIVE",
      regimeBadge: "CIRCUIT BREAKER",
      statusTitle: reason || "DEFENSIVE (BTC Dump Active)",
    };
  }

  // 3. CAUTION (High Volatility Swings)
  if (code === "CAUTION" || regime === "VOLATILE" || reason.toUpperCase().includes("CAUTION") || reason.toUpperCase().includes("HIGH VOLATILITY")) {
    return {
      border: "border-amber-500/60 bg-amber-950/40 text-amber-300 shadow-amber-500/20",
      iconColor: "text-amber-400",
      dotColor: "bg-amber-500",
      pingColor: "bg-amber-400",
      isAlert: false,
      badgeBg: "bg-amber-500/20 text-amber-300 border-amber-500/50 shadow-sm shadow-amber-500/10",
      glowBg: "bg-amber-500/20",
      headline: "⚡ Elevated Market Volatility Caution",
      subline: "BTC 15M/1H experiencing rapid price swings. Position sizing calibrated defensively with strict stops.",
      label: "CAUTION",
      regimeBadge: "HIGH VOLATILITY",
      statusTitle: reason || "CAUTION (High Volatility)",
    };
  }

  // 4. DIP ACCUMULATION (Oversold Bounce in Macro Bull Trend)
  if (reason.toUpperCase().includes("DIP ACCUMULATION") || regime.includes("ACCUMULATION")) {
    return {
      border: "border-teal-500/60 bg-teal-950/40 text-teal-300 shadow-teal-500/25",
      iconColor: "text-teal-400",
      dotColor: "bg-teal-500",
      pingColor: "bg-teal-400",
      isAlert: false,
      badgeBg: "bg-teal-500/20 text-teal-300 border-teal-500/50 shadow-sm shadow-teal-500/15",
      glowBg: "bg-teal-500/20",
      headline: "💎 Oversold Dip Accumulation Zone",
      subline: "BTC bouncing off dynamic support from oversold conditions. High-probability dip-buy setups active.",
      label: "DIP ACCUMULATION",
      regimeBadge: "ACCUMULATION",
      statusTitle: reason || "DIP ACCUMULATION",
    };
  }

  // 5. BULL_MOMENTUM / BULLISH EXPANSION
  if (code === "BULL_MOMENTUM" || regime === "BULLISH" || reason.toUpperCase().includes("BULLISH")) {
    return {
      border: "border-emerald-500/60 bg-emerald-950/40 text-emerald-300 shadow-emerald-500/25",
      iconColor: "text-emerald-400",
      dotColor: "bg-emerald-500",
      pingColor: "bg-emerald-400",
      isAlert: false,
      badgeBg: "bg-emerald-500/20 text-emerald-300 border-emerald-500/50 shadow-sm shadow-emerald-500/15",
      glowBg: "bg-emerald-500/20",
      headline: "🚀 Bullish Market Expansion Active",
      subline: "BTC momentum is accelerating upwards above key EMAs. Long continuation and breakout setups active.",
      label: "BULLISH EXPANSION",
      regimeBadge: "BULLISH REGIME",
      statusTitle: reason || "BULLISH EXPANSION",
    };
  }

  // 6. BEAR_MOMENTUM / BEARISH DRIFT / BREAKDOWN
  if (code === "BEAR_MOMENTUM" || regime === "BEARISH" || reason.toUpperCase().includes("BEARISH")) {
    return {
      border: "border-orange-500/60 bg-orange-950/40 text-orange-300 shadow-orange-500/20",
      iconColor: "text-orange-400",
      dotColor: "bg-orange-500",
      pingColor: "bg-orange-400",
      isAlert: false,
      badgeBg: "bg-orange-500/20 text-orange-300 border-orange-500/50 shadow-sm shadow-orange-500/15",
      glowBg: "bg-orange-500/20",
      headline: "🐻 Bearish Breakdown & Selling Pressure",
      subline: "BTC trading below key EMAs with negative drift. Altcoin longs filtered; short setups prioritized.",
      label: "BEARISH DRIFT",
      regimeBadge: "BEARISH REGIME",
      statusTitle: reason || "BEARISH BREAKDOWN",
    };
  }

  // 7. CONSOLIDATION / RANGE-BOUND (Volatility Squeeze)
  if (code === "CONSOLIDATION" || regime === "CONSOLIDATION" || reason.toUpperCase().includes("RANGE") || reason.toUpperCase().includes("CONSOLIDAT") || reason.toUpperCase().includes("SQUEEZE")) {
    return {
      border: "border-indigo-500/50 bg-indigo-950/40 text-indigo-300 shadow-indigo-500/20",
      iconColor: "text-indigo-400",
      dotColor: "bg-indigo-500",
      pingColor: "bg-indigo-400",
      isAlert: false,
      badgeBg: "bg-indigo-500/20 text-indigo-300 border-indigo-500/50 shadow-sm shadow-indigo-500/15",
      glowBg: "bg-indigo-500/20",
      headline: "💤 Range-Bound Market Consolidation",
      subline: "BTC coiling inside tight Bollinger Bands. Low-beta mean reversion and range scalp setups active.",
      label: "RANGE CONSOLIDATION",
      regimeBadge: "CONSOLIDATING",
      statusTitle: reason || "RANGE CONSOLIDATION",
    };
  }

  // 8. NORMAL / BALANCED EQUILIBRIUM
  return {
    border: "border-cyan-500/40 bg-cyan-950/30 text-cyan-300 shadow-cyan-500/10",
    iconColor: "text-cyan-400",
    dotColor: "bg-cyan-500",
    pingColor: "bg-cyan-400",
    isAlert: false,
    badgeBg: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40 shadow-sm shadow-cyan-500/10",
    glowBg: "bg-cyan-500/10",
    headline: "⚖️ Balanced Market Equilibrium",
    subline: "BTC multi-timeframe volatility is stable and balanced. Multi-horizon quantitative setups active.",
    label: "BALANCED EQUILIBRIUM",
    regimeBadge: "BALANCED",
    statusTitle: reason || "BALANCED MARKET",
  };
}
