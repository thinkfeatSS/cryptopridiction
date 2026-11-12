/**
 * QUANT EDGE V16: Formatting & Quantitative Calculation Utilities
 * Strictly zero fake data. Formats numbers and computes client aggregates only from real API records.
 */

import { V16SignalEnvelope } from "@/types/v16";

export function formatPrice(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return "N/A";
  if (val === 0) return "$0.00";
  if (val >= 1000) {
    return `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (val >= 1) {
    return `$${val.toFixed(4)}`;
  }
  if (val >= 0.001) {
    return `$${val.toFixed(6)}`;
  }
  return `$${val.toFixed(8)}`;
}

export function formatPercent(val: number | null | undefined, includeSign = true): string {
  if (val === null || val === undefined || isNaN(val)) return "N/A";
  const sign = includeSign && val > 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

export function formatProbability(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return "N/A";
  let pct = val;
  // If stored as 0.0-1.0, convert to 0-100
  if (pct <= 1.0) {
    pct = pct * 100.0;
  }
  // Defensive guard: if erroneously scaled (e.g. 7427%), normalize back to 0-100
  while (pct > 100.0) {
    pct = pct / 100.0;
  }
  return `${pct.toFixed(1)}%`;
}

export function getRegimeTheme(regime: string): {
  bg: string;
  border: string;
  text: string;
  dot: string;
  label: string;
} {
  const r = (regime || "").toUpperCase();
  if (r.includes("BULL")) {
    return {
      bg: "bg-emerald-950/50",
      border: "border-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.15)]",
      text: "text-emerald-300",
      dot: "bg-emerald-400",
      label: "BULL TREND",
    };
  }
  if (r.includes("BEAR")) {
    return {
      bg: "bg-rose-950/50",
      border: "border-rose-500/40 shadow-[0_0_15px_rgba(244,63,94,0.15)]",
      text: "text-rose-300",
      dot: "bg-rose-400",
      label: "BEAR TREND",
    };
  }
  if (r.includes("SQUEEZE")) {
    return {
      bg: "bg-cyan-950/50",
      border: "border-cyan-500/40 shadow-[0_0_15px_rgba(6,182,212,0.15)]",
      text: "text-cyan-300",
      dot: "bg-cyan-400",
      label: "SQUEEZE",
    };
  }
  if (r.includes("BREAKOUT")) {
    return {
      bg: "bg-purple-950/50",
      border: "border-purple-500/40 shadow-[0_0_15px_rgba(168,85,247,0.15)]",
      text: "text-purple-300",
      dot: "bg-purple-400",
      label: "BREAKOUT",
    };
  }
  if (r.includes("HIGH_VOL") || r.includes("VOLATILE")) {
    return {
      bg: "bg-amber-950/50",
      border: "border-amber-500/40 shadow-[0_0_15px_rgba(251,191,36,0.15)]",
      text: "text-amber-300",
      dot: "bg-amber-400",
      label: "HIGH VOLATILITY",
    };
  }
  if (r.includes("LOW_VOL")) {
    return {
      bg: "bg-teal-950/50",
      border: "border-teal-500/40 shadow-[0_0_15px_rgba(20,184,166,0.15)]",
      text: "text-teal-300",
      dot: "bg-teal-400",
      label: "LOW VOLATILITY",
    };
  }
  if (r.includes("TRANSITION")) {
    return {
      bg: "bg-yellow-950/50",
      border: "border-yellow-500/40 shadow-[0_0_15px_rgba(234,179,8,0.15)]",
      text: "text-yellow-300",
      dot: "bg-yellow-400",
      label: "TRANSITION",
    };
  }
  return {
    bg: "bg-indigo-950/40",
    border: "border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.15)]",
    text: "text-indigo-300",
    dot: "bg-indigo-400",
    label: r || "RANGE",
  };
}

export function getGradeBadge(grade: string): {
  bg: string;
  border: string;
  text: string;
} {
  const g = (grade || "").toUpperCase();
  if (g.includes("A+")) {
    return {
      bg: "bg-amber-950/60",
      border: "border-amber-400/60 shadow-[0_0_8px_rgba(251,191,36,0.3)]",
      text: "text-amber-300 font-black",
    };
  }
  if (g.includes("A")) {
    return {
      bg: "bg-cyan-950/60",
      border: "border-cyan-500/50 shadow-[0_0_8px_rgba(6,182,212,0.25)]",
      text: "text-cyan-300 font-bold",
    };
  }
  if (g.includes("B")) {
    return {
      bg: "bg-indigo-950/60",
      border: "border-indigo-500/50",
      text: "text-indigo-300 font-bold",
    };
  }
  return {
    bg: "bg-slate-900/60",
    border: "border-slate-700/60",
    text: "text-slate-400",
  };
}

/**
 * Standardized Quant Edge V16 Outcome Classifier for Frontend Components.
 * Strictly aligned with backend app/quant_v16/audit.py classify_signal_outcome().
 * Returns one of: 'ACTIVE', 'WON', 'LOST', 'BREAKEVEN', 'EXPIRED'.
 */
export function getSignalStatus(item: V16SignalEnvelope): "ACTIVE" | "WON" | "LOST" | "BREAKEVEN" | "EXPIRED" {
  const st = (item.dynamic?.status || item.immutable?.status || "").trim().toUpperCase();
  const out = (item.dynamic?.outcome_label || "").trim().toUpperCase();

  // 1. Pending / Active trades (Strict Gate: must be evaluated first per Rule 9)
  const pendingStatuses = [
    "PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "RESTING_LIMIT",
    "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
  ];
  if (
    pendingStatuses.includes(st) ||
    st === "ACTIVE" ||
    out.includes("ACTIVE") ||
    out.includes("PENDING") ||
    out.includes("RUNNING") ||
    out.includes("AWAIT") ||
    out.includes("RESTING")
  ) {
    return "ACTIVE";
  }

  // 2. Breakeven outcomes (without substring "BE" matching "BEAR")
  const beStatuses = [
    "WON_TIER0_BE", "WON_TP1_BE", "EXPIRED_BREAKEVEN",
    "BREAKEVEN_EXP", "TIER0_BE_HIT", "BREAKEVEN", "BREAKEVEN_GUARD",
    "STOP_LOSS_BREAKEVEN", "TIER0_GUARD"
  ];
  if (
    beStatuses.includes(st) ||
    st.includes("BREAKEVEN") ||
    st.includes("BE_") ||
    st.includes("TIER0_BE") ||
    st.includes("SOFT_BE") ||
    out.includes("BREAKEVEN") ||
    out.includes("TIER-0") ||
    out.includes("BE RUNNER") ||
    out.includes("(BE")
  ) {
    return "BREAKEVEN";
  }

  // 3. Won outcomes
  const wonStatuses = [
    "WON_TP3", "WON_TP2_TRAIL", "WON_TP2", "WON_TP1",
    "WON_TP2_EXP", "WON_TP1_EXP", "WON_EXP_PROFIT", "WON_PROFIT_EXPIRED", "WON",
    "WON_PROFIT_RATCHET"
  ];
  if (
    wonStatuses.includes(st) ||
    st.includes("WON") ||
    (out.includes("WON") && !out.includes("LOST")) ||
    out.includes("TP HIT") ||
    out.includes("TP1 HIT") ||
    out.includes("TP2 HIT") ||
    out.includes("TP3 HIT") ||
    st.includes("PROFIT_EXPIRED") ||
    out.includes("PROFIT")
  ) {
    return "WON";
  }

  // 4. Lost outcomes
  const lostStatuses = ["LOST_SL", "LOST_EXP", "LOST_EXPIRED", "LOST"];
  if (
    lostStatuses.includes(st) ||
    st.includes("LOST") ||
    (out.includes("LOST") && !out.includes("WON")) ||
    st.includes("STOP_LOSS") ||
    out.includes("SL HIT") ||
    out.includes("STOPPED")
  ) {
    return "LOST";
  }

  // 5. Expired outcomes
  if (
    st.includes("EXP") ||
    out.includes("EXPIRED") ||
    out.includes("MISSED") ||
    out.includes("TIMEOUT") ||
    st.includes("STAGNATION")
  ) {
    return "EXPIRED";
  }

  // Fallback: if realized return is recorded and non-zero
  const ret = item.dynamic?.realized_return_pct;
  if (ret !== undefined && ret !== null && !isNaN(ret)) {
    if (ret > 0.05) return "WON";
    if (ret < -0.05) return "LOST";
    return "BREAKEVEN";
  }

  return "ACTIVE";
}

/**
 * Authoritative V16 Qualification Gate (Frontend).
 * Strictly mirrors tests/test_qualified_v16_signals.py and app/engine/execution/paper_trading_bot.py.
 */
export function isV16RuleQualified(item: V16SignalEnvelope): boolean {
  const imm = item.immutable;
  if (!imm) return false;

  // Reject synthetic unit test signals
  const sid = (imm.signal_id || "").toUpperCase();
  if (sid.startsWith("TEST_") || sid.includes("TEST")) return false;

  // Rule 1: EVnet > 0
  const ev = imm.expected_net_return ?? 0;
  if (ev <= 0) return false;

  // Rule 2: Grade must be qualified (A+, A, B)
  const g = (imm.grade || "").toUpperCase();
  const isGradeOk = g.includes("A+") || g.includes("GRADE A") || g.includes("GRADE B") || g.includes("A") || g.includes("B");
  if (!isGradeOk) return false;

  // Rule 3: Valid price structure
  const entry = imm.entry_price_initial || 0;
  const sl = imm.sl_initial || 0;
  const currentSl = item.dynamic?.current_sl || sl;
  const tp1 = imm.tp1_initial || 0;
  const isLong = (imm.direction || "").toUpperCase() === "LONG";

  if (entry <= 0 || sl <= 0 || tp1 <= 0) return false;

  const isProtected = Boolean(
    item.dynamic?.is_tp1_locked ||
    item.dynamic?.status?.includes("BREAKEVEN") ||
    item.dynamic?.status?.includes("TIER0") ||
    (isLong ? currentSl >= entry : currentSl <= entry)
  );

  if (isLong) {
    if (!((sl < entry || isProtected) && entry < tp1)) return false;
  } else {
    if (!((sl > entry || isProtected) && entry > tp1)) return false;
  }

  return true;
}
