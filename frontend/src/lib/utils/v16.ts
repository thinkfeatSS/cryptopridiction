/**
 * QUANT EDGE V16: Formatting & Quantitative Calculation Utilities
 * Strictly zero fake data. Formats numbers and computes client aggregates only from real API records.
 */

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
