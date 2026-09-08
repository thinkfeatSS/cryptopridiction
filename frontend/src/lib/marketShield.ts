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
  statusTitle: string;
}

export function getShieldTheme(shield?: BtcMarketShield): ShieldTheme {
  const code = (shield?.status_code || "").toUpperCase();
  const isActive = Boolean(shield?.active);
  const reason = shield?.reason || "";

  // 1. ALERT_DUMP / SEVERE DUMP
  if (code === "ALERT_DUMP" || reason.toUpperCase().includes("SEVERE DUMP")) {
    return {
      border: "border-red-600/80 bg-red-950/60 text-red-200 shadow-red-600/30 animate-pulse",
      iconColor: "text-red-400",
      dotColor: "bg-red-500",
      pingColor: "bg-red-400",
      isAlert: true,
      badgeBg: "bg-red-500/20 text-red-200 border-red-500/60 shadow-sm shadow-red-500/20",
      glowBg: "bg-red-500/25",
      headline: "🚨 Severe Systemic Dump Detected",
      subline: "BTC systemic sell-off in progress. Emergency risk-off and capital preservation active across all assets.",
      label: "ALERT_DUMP",
      statusTitle: reason || "SEVERE DUMP (High Volatility Flush)",
    };
  }

  // 2. DEFENSIVE (BTC Dump / Circuit Breaker Active)
  if (code === "DEFENSIVE" || isActive || reason.toUpperCase().includes("DEFENSIVE")) {
    return {
      border: "border-rose-500/60 bg-rose-950/50 text-rose-300 shadow-rose-500/20 animate-pulse",
      iconColor: "text-rose-400",
      dotColor: "bg-rose-500",
      pingColor: "bg-rose-400",
      isAlert: true,
      badgeBg: "bg-rose-500/20 text-rose-300 border-rose-500/50 shadow-sm shadow-rose-500/20",
      glowBg: "bg-rose-500/20",
      headline: "⚠️ BTC Market Beta Circuit Breaker Active",
      subline: "Altcoin Long executions temporarily paused to prevent correlated cascade stop-outs. Short setups active.",
      label: "DEFENSIVE",
      statusTitle: reason || "DEFENSIVE (BTC Dump Active)",
    };
  }

  // 3. CAUTION (High Volatility)
  if (code === "CAUTION" || reason.toUpperCase().includes("CAUTION")) {
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
      statusTitle: reason || "CAUTION (High Volatility)",
    };
  }

  // 4. BULL_MOMENTUM / BULLISH EXPANSION
  if (code === "BULL_MOMENTUM" || reason.toUpperCase().includes("BULLISH")) {
    return {
      border: "border-emerald-500/50 bg-emerald-950/40 text-emerald-300 shadow-emerald-500/20",
      iconColor: "text-emerald-400",
      dotColor: "bg-emerald-500",
      pingColor: "bg-emerald-400",
      isAlert: false,
      badgeBg: "bg-emerald-500/20 text-emerald-300 border-emerald-500/50 shadow-sm shadow-emerald-500/10",
      glowBg: "bg-emerald-500/20",
      headline: "🚀 Bullish Market Expansion Active",
      subline: "BTC momentum is accelerating upwards. Long continuation and breakout setups active across altcoins.",
      label: "BULLISH EXPANSION",
      statusTitle: reason || "BULLISH EXPANSION",
    };
  }

  // 5. NORMAL (Market Stable)
  return {
    border: "border-cyan-500/30 bg-cyan-950/30 text-cyan-300 shadow-cyan-500/10",
    iconColor: "text-cyan-400",
    dotColor: "bg-emerald-500",
    pingColor: "bg-emerald-400",
    isAlert: false,
    badgeBg: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40 shadow-sm shadow-emerald-500/10",
    glowBg: "bg-cyan-500/10",
    headline: "🛡️ Real-time Cross-Asset Safeguard Active",
    subline: "BTC 15M/1H volatility is stable. Full multi-horizon entries permitted across all 100 assets.",
    label: "NORMAL",
    statusTitle: reason || "NORMAL (Market Stable)",
  };
}
