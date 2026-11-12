"use client";

import React, { useState, useMemo } from "react";
import { useV16Signals } from "@/hooks/useV16Data";
import { V16SignalEnvelope } from "@/types/v16";
import { formatPrice, formatPercent, formatProbability, getGradeBadge, getRegimeTheme } from "@/lib/utils/v16";
import V16SignalCard from "@/components/v16/V16SignalCard";
import V16SignalDetailModal from "@/components/v16/V16SignalDetailModal";
import {
  Search,
  Filter,
  Download,
  CheckCircle2,
  XCircle,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  ShieldCheck,
  ShieldAlert,
  Lock,
  Layers,
  BarChart2,
  Table,
  LayoutGrid,
  FileSpreadsheet
} from "lucide-react";

export default function V16SignalsAuditLedger() {
  const { data, isLoading, refetch, isFetching } = useV16Signals();
  const allSignals = data?.signals || [];

  const [selectedSignal, setSelectedSignal] = useState<V16SignalEnvelope | null>(null);
  const [viewMode, setViewMode] = useState<"TABLE" | "CARDS">("TABLE");

  // Filter states
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [directionFilter, setDirectionFilter] = useState<string>("ALL");
  const [horizonFilter, setHorizonFilter] = useState<string>("ALL");
  const [gradeFilter, setGradeFilter] = useState<string>("ALL");
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(25);

  // STRICT V16 FILTER: Must strictly be V16 signals (has valid V16 immutable structure, model_version v16.0 or expected_net_return defined)
  const v16Signals = useMemo(() => {
    return allSignals.filter((s) => {
      const imm = s.immutable;
      if (!imm) return false;
      const isV16 =
        imm.model_version?.toLowerCase().includes("v16") ||
        imm.strategy_version?.toLowerCase().includes("v16") ||
        (imm.expected_net_return !== undefined && imm.p_tp1 !== undefined);
      return isV16;
    });
  }, [allSignals]);

  // Deterministic status classifier strictly aligned with app/quant_v16/audit.py
  const getSignalStatus = (item: V16SignalEnvelope): "ACTIVE" | "WON" | "LOST" | "BREAKEVEN" | "EXPIRED" => {
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

    // 2. Breakeven outcomes
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
  };

  // Status Counts
  const counts = useMemo(() => {
    let active = 0;
    let won = 0;
    let lost = 0;
    let breakeven = 0;
    let expired = 0;

    v16Signals.forEach((s) => {
      const cat = getSignalStatus(s);
      if (cat === "WON") won++;
      else if (cat === "LOST") lost++;
      else if (cat === "BREAKEVEN") breakeven++;
      else if (cat === "EXPIRED") expired++;
      else active++;
    });

    const evaluatedTotal = won + lost + breakeven + expired;
    const decisiveTotal = won + lost;

    return {
      active,
      won,
      lost,
      breakeven,
      expired,
      evaluatedTotal,
      decisiveTotal,
      total: v16Signals.length
    };
  }, [v16Signals]);

  // Executive V16 KPI Metrics
  const kpis = useMemo(() => {
    const total = v16Signals.length;
    if (total === 0) {
      return {
        totalSignals: 0,
        activeSignals: 0,
        evaluatedTotal: 0,
        decisiveTotal: 0,
        won: 0,
        lost: 0,
        breakeven: 0,
        expired: 0,
        decisiveWinRate: null as number | null,
        totalWinRate: null as number | null,
        gradeAPlusWinRate: null as number | null,
        gradeAPlusCount: 0,
        gradeAPlusWon: 0,
        gradeAPlusDecisive: 0,
        avgNetEv: 0,
        avgPtp1: 0,
        cumulativeReturn: 0,
      };
    }

    const won = counts.won;
    const lost = counts.lost;
    const decisiveTotal = counts.decisiveTotal; // won + lost
    const evaluatedTotal = counts.evaluatedTotal; // won + lost + breakeven + expired

    // Decisive Win Rate: Won / (Won + Lost)
    // When decisiveTotal === 0, win rate is mathematically undefined (null -> display '—')
    const decisiveWinRate = decisiveTotal > 0 ? (won / decisiveTotal) * 100 : null;

    // Total Closed/Evaluated Win Rate: Won / All Evaluated Signals (per Section 4.1 & test_suite_engine.py:781)
    // Active/Pending signals MUST NEVER dilute evaluated win rate!
    // When evaluatedTotal === 0, win rate is null (display '—')
    const totalWinRate = evaluatedTotal > 0 ? (won / evaluatedTotal) * 100 : null;

    // Grade A+ Win Rate
    const gradeAPlusSignals = v16Signals.filter((s) => (s.immutable.grade || "").toUpperCase().includes("A+"));
    const gradeAPlusWon = gradeAPlusSignals.filter((s) => getSignalStatus(s) === "WON").length;
    const gradeAPlusLost = gradeAPlusSignals.filter((s) => getSignalStatus(s) === "LOST").length;
    const gradeAPlusDecisive = gradeAPlusWon + gradeAPlusLost;
    const gradeAPlusEvaluated = gradeAPlusSignals.filter((s) => getSignalStatus(s) !== "ACTIVE").length;
    const gradeAPlusWinRate = gradeAPlusDecisive > 0
      ? (gradeAPlusWon / gradeAPlusDecisive) * 100
      : (gradeAPlusEvaluated > 0 ? (gradeAPlusWon / gradeAPlusEvaluated) * 100 : null);

    // Averages across all audited signals
    const sumNetEv = v16Signals.reduce((acc, s) => acc + (s.immutable.expected_net_return || 0), 0);
    const sumPtp1 = v16Signals.reduce((acc, s) => {
      const p = s.immutable.p_tp1 || 0;
      return acc + (p > 1.0 ? p / 100.0 : p);
    }, 0);

    // Cumulative Return %: sum of realized returns of resolved/evaluated signals ONLY (Rule 9)
    const evaluatedSignals = v16Signals.filter((s) => getSignalStatus(s) !== "ACTIVE");
    const sumReturn = evaluatedSignals.reduce((acc, s) => {
      const pnl = s.dynamic?.realized_return_pct ?? 0;
      return acc + pnl;
    }, 0);

    return {
      totalSignals: total,
      activeSignals: counts.active,
      evaluatedTotal,
      decisiveTotal,
      won,
      lost,
      breakeven: counts.breakeven,
      expired: counts.expired,
      decisiveWinRate,
      totalWinRate,
      gradeAPlusWinRate,
      gradeAPlusCount: gradeAPlusSignals.length,
      gradeAPlusWon,
      gradeAPlusDecisive,
      avgNetEv: sumNetEv / total,
      avgPtp1: (sumPtp1 / total) * 100,
      cumulativeReturn: sumReturn,
    };
  }, [v16Signals, counts]);

  // Horizons available
  const horizons = useMemo(() => {
    const set = new Set<string>();
    v16Signals.forEach((s) => {
      if (s.immutable?.horizon) set.add(s.immutable.horizon);
    });
    const standardOrder = ["5M", "15M", "1H", "4H", "12H", "24H", "7D", "15D", "1M"];
    return standardOrder.filter((h) => set.has(h)).concat(Array.from(set).filter((h) => !standardOrder.includes(h)));
  }, [v16Signals]);

  // Filtered signals
  const filteredSignals = useMemo(() => {
    return v16Signals
      .filter((s) => {
        const imm = s.immutable;
        const sym = (imm.symbol || "").toUpperCase();
        const sid = (imm.signal_id || "").toUpperCase();
        const tid = (imm.trade_thesis_id || "").toUpperCase();
        const sQuery = search.trim().toUpperCase();

        if (sQuery && !sym.includes(sQuery) && !sid.includes(sQuery) && !tid.includes(sQuery)) {
          return false;
        }

        // Status
        if (statusFilter !== "ALL") {
          const st = getSignalStatus(s);
          if (statusFilter === "ACTIVE" && st !== "ACTIVE") return false;
          if (statusFilter === "WON" && st !== "WON") return false;
          if (statusFilter === "LOST" && st !== "LOST") return false;
          if (statusFilter === "BREAKEVEN" && st !== "BREAKEVEN") return false;
          if (statusFilter === "EXPIRED" && st !== "EXPIRED") return false;
        }

        // Direction
        if (directionFilter !== "ALL" && (imm.direction || "").toUpperCase() !== directionFilter) {
          return false;
        }

        // Horizon
        if (horizonFilter !== "ALL" && imm.horizon !== horizonFilter) {
          return false;
        }

        // Grade
        if (gradeFilter !== "ALL") {
          const g = (imm.grade || "").toUpperCase();
          if (gradeFilter === "A_PLUS" && !g.includes("A+")) return false;
          if (gradeFilter === "A" && (!g.includes("A") || g.includes("A+"))) return false;
          if (gradeFilter === "B" && !g.includes("B")) return false;
        }

        return true;
      })
      .sort((a, b) => {
        // Most recent first
        const tA = a.immutable.signal_generated_at || "";
        const tB = b.immutable.signal_generated_at || "";
        return tB.localeCompare(tA);
      });
  }, [v16Signals, search, statusFilter, directionFilter, horizonFilter, gradeFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredSignals.length / pageSize));
  const paginatedSignals = useMemo(() => {
    return filteredSignals.slice((page - 1) * pageSize, page * pageSize);
  }, [filteredSignals, page, pageSize]);

  // CSV Export Function
  const handleExportCsv = () => {
    if (filteredSignals.length === 0) return;

    const headers = [
      "Signal ID",
      "Trade Thesis ID",
      "Timestamp UTC",
      "Symbol",
      "Direction",
      "Horizon",
      "Quality Grade",
      "Regime",
      "Entry Price Initial",
      "Current Price",
      "Stop Loss",
      "TP1 Price",
      "TP2 Price",
      "TP3 Price",
      "Expected Net EV %",
      "Win Prob P(TP1) %",
      "Risk Reward",
      "Status",
      "Outcome Label",
      "Unrealized PnL %",
      "MFE %",
      "MAE %",
    ];

    const rows = filteredSignals.map((s) => [
      `"${s.immutable.signal_id}"`,
      `"${s.immutable.trade_thesis_id}"`,
      `"${s.immutable.signal_generated_at}"`,
      `"${s.immutable.symbol}"`,
      `"${s.immutable.direction}"`,
      `"${s.immutable.horizon}"`,
      `"${s.immutable.grade}"`,
      `"${s.immutable.regime || 'RANGE'}"`,
      s.immutable.entry_price_initial,
      s.dynamic?.current_price || s.immutable.entry_price_initial,
      s.dynamic?.current_sl || s.immutable.sl_initial,
      s.immutable.tp1_initial,
      s.immutable.tp2_initial,
      s.immutable.tp3_initial,
      s.immutable.expected_net_return,
      s.immutable.p_tp1,
      s.immutable.risk_reward,
      `"${s.dynamic?.status || s.immutable.status}"`,
      `"${s.dynamic?.outcome_label || ''}"`,
      s.dynamic?.unrealized_net_pnl_pct || 0,
      s.dynamic?.mfe_pct || 0,
      s.dynamic?.mae_pct || 0,
    ]);

    const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `quant_edge_v16_signals_audit_ledger_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-6">
      {/* ========================================================= */}
      {/* 1. HEADER SECTION */}
      {/* ========================================================= */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="p-2 rounded-xl bg-cyan-950/70 border border-cyan-500/40 text-cyan-400">
              <BarChart2 className="w-5 h-5" />
            </span>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-white font-mono uppercase">
              Quant Edge V16 Signals Audit Ledger
            </h1>
          </div>
          <p className="text-xs text-slate-400 font-mono mt-1">
            Authoritative institutional audit ledger tracking calibrated V16 signals with strict price geometry, mathematical EVnet hurdle, and real-time outcome resolution.
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start md:self-auto font-mono">
          <button
            onClick={handleExportCsv}
            disabled={filteredSignals.length === 0}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-emerald-950/70 border border-emerald-500/40 hover:bg-emerald-900/80 text-xs text-emerald-300 font-bold transition-all shadow-sm disabled:opacity-50"
          >
            <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
            <span>Export V16 CSV</span>
          </button>

          <button
            onClick={() => refetch()}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-800 hover:border-cyan-500/40 text-xs text-slate-300 hover:text-cyan-300 font-bold transition-all shadow-sm"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin text-cyan-400" : "text-slate-400"}`} />
            <span>Sync Live</span>
          </button>
        </div>
      </div>

      {/* ========================================================= */}
      {/* 2. EXECUTIVE V16 AUDIT KPI METRICS BAR */}
      {/* ========================================================= */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Total Audited Signals */}
        <div className="p-3.5 rounded-2xl bg-slate-900/60 border border-slate-800/80 font-mono">
          <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Total Audited</span>
          <div className="text-lg sm:text-xl font-black text-white mt-1">
            {kpis.totalSignals}
          </div>
          <span className="text-[10px] text-cyan-400 font-bold">
            {kpis.activeSignals > 0 ? `${kpis.activeSignals} Active · ${kpis.evaluatedTotal} Evaluated` : "100% V16 Qualified"}
          </span>
        </div>

        {/* Decisive Win Rate */}
        <div className="p-3.5 rounded-2xl bg-slate-900/60 border border-slate-800/80 font-mono">
          <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Decisive Win Rate</span>
          <div className={`text-lg sm:text-xl font-black mt-1 ${kpis.decisiveWinRate !== null ? (kpis.decisiveWinRate >= 50 ? "text-emerald-400" : "text-amber-400") : "text-slate-400"}`}>
            {kpis.decisiveWinRate !== null ? `${kpis.decisiveWinRate.toFixed(1)}%` : "—"}
          </div>
          <span className="text-[10px] text-slate-400">
            {kpis.decisiveTotal > 0 ? `${kpis.won} Won / ${kpis.decisiveTotal} Decisive` : "0 / 0 Decisive (Pending)"}
          </span>
        </div>

        {/* Total Win Rate */}
        <div className="p-3.5 rounded-2xl bg-slate-900/60 border border-slate-800/80 font-mono">
          <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Total Win Rate</span>
          <div className={`text-lg sm:text-xl font-black mt-1 ${kpis.totalWinRate !== null ? (kpis.totalWinRate >= 50 ? "text-cyan-300" : "text-amber-300") : "text-slate-400"}`}>
            {kpis.totalWinRate !== null ? `${kpis.totalWinRate.toFixed(1)}%` : "—"}
          </div>
          <span className="text-[10px] text-slate-400">
            {kpis.evaluatedTotal > 0 ? `${kpis.won} Won / ${kpis.evaluatedTotal} Evaluated` : "0 Evaluated Signals"}
          </span>
        </div>

        {/* Grade A+ Win Rate */}
        <div className="p-3.5 rounded-2xl bg-slate-900/60 border border-slate-800/80 font-mono">
          <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Grade A+ Win Rate</span>
          <div className={`text-lg sm:text-xl font-black mt-1 ${kpis.gradeAPlusWinRate !== null ? "text-amber-300" : "text-slate-400"}`}>
            {kpis.gradeAPlusWinRate !== null ? `${kpis.gradeAPlusWinRate.toFixed(1)}%` : "—"}
          </div>
          <span className="text-[10px] text-slate-400">
            {kpis.gradeAPlusDecisive > 0
              ? `${kpis.gradeAPlusWon} Won / ${kpis.gradeAPlusDecisive} Decisive`
              : (kpis.gradeAPlusCount > 0 ? `${kpis.gradeAPlusCount} Active (0 Decisive)` : "0 A+ Setups Audited")}
          </span>
        </div>

        {/* Average Net EV */}
        <div className="p-3.5 rounded-2xl bg-slate-900/60 border border-slate-800/80 font-mono">
          <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Avg Expected Edge</span>
          <div className={`text-lg sm:text-xl font-black mt-1 ${kpis.avgNetEv >= 0 ? "text-cyan-400" : "text-rose-400"}`}>
            {kpis.totalSignals > 0 ? `${kpis.avgNetEv >= 0 ? "+" : ""}${kpis.avgNetEv.toFixed(2)}%` : "—"}
          </div>
          <span className="text-[10px] text-slate-400">Net EV After Friction</span>
        </div>

        {/* Average Win Prob */}
        <div className="p-3.5 rounded-2xl bg-slate-900/60 border border-slate-800/80 font-mono">
          <span className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Avg Win Prob</span>
          <div className="text-lg sm:text-xl font-black text-emerald-400 mt-1">
            {kpis.totalSignals > 0 ? `${kpis.avgPtp1.toFixed(1)}%` : "—"}
          </div>
          <span className="text-[10px] text-slate-400">Calibrated P(TP1)</span>
        </div>
      </div>

      {/* ========================================================= */}
      {/* 3. AUDIT FILTER TOOLBAR */}
      {/* ========================================================= */}
      <div className="p-4 rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl shadow-lg flex flex-col gap-3.5">
        {/* Status Filter Tabs */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-slate-900/90 border border-slate-800">
            <button
              onClick={() => { setStatusFilter("ALL"); setPage(1); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "ALL"
                  ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>ALL AUDITED</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-indigo-300">
                {counts.total}
              </span>
            </button>

            <button
              onClick={() => { setStatusFilter("ACTIVE"); setPage(1); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "ACTIVE"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>ACTIVE / RUNNING</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-cyan-300">
                {counts.active}
              </span>
            </button>

            <button
              onClick={() => { setStatusFilter("WON"); setPage(1); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "WON"
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>WON (TP / PROFIT)</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-emerald-300">
                {counts.won}
              </span>
            </button>

            <button
              onClick={() => { setStatusFilter("BREAKEVEN"); setPage(1); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "BREAKEVEN"
                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>BREAKEVEN DEFENSE</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-amber-300">
                {counts.breakeven}
              </span>
            </button>

            <button
              onClick={() => { setStatusFilter("LOST"); setPage(1); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "LOST"
                  ? "bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>STOPPED (LOST)</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-rose-300">
                {counts.lost}
              </span>
            </button>

            <button
              onClick={() => { setStatusFilter("EXPIRED"); setPage(1); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "EXPIRED"
                  ? "bg-slate-700/40 text-slate-200 border border-slate-600 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>EXPIRED</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-slate-300">
                {counts.expired}
              </span>
            </button>
          </div>

          {/* View Mode Toggle: Table vs Cards */}
          <div className="flex items-center gap-1 p-1 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
            <button
              onClick={() => setViewMode("TABLE")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all ${
                viewMode === "TABLE"
                  ? "bg-gradient-to-r from-cyan-600/30 to-indigo-600/30 text-cyan-300 border border-cyan-500/50 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Table className="w-3.5 h-3.5 text-cyan-400" />
              <span>Audit Table</span>
            </button>

            <button
              onClick={() => setViewMode("CARDS")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all ${
                viewMode === "CARDS"
                  ? "bg-gradient-to-r from-cyan-600/30 to-indigo-600/30 text-cyan-300 border border-cyan-500/50 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5 text-cyan-400" />
              <span>Audit Cards</span>
            </button>
          </div>
        </div>

        {/* Search & Sub-filters */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-800/60 font-mono">
          <div className="flex flex-wrap items-center gap-2 flex-1">
            {/* Search Input */}
            <div className="relative min-w-[200px] max-w-sm flex-1">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder="Search symbol, signal ID, thesis..."
                className="w-full bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 transition-colors"
              />
            </div>

            {/* Direction Filter */}
            <div className="flex items-center gap-1 p-0.5 rounded-lg bg-slate-950/80 border border-slate-800 text-[11px] font-bold">
              <button
                onClick={() => { setDirectionFilter("ALL"); setPage(1); }}
                className={`px-2.5 py-1 rounded-md transition-all ${directionFilter === "ALL" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"}`}
              >
                ALL
              </button>
              <button
                onClick={() => { setDirectionFilter("LONG"); setPage(1); }}
                className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1 ${directionFilter === "LONG" ? "bg-emerald-950 text-emerald-400 border border-emerald-500/30" : "text-slate-400 hover:text-emerald-400"}`}
              >
                <TrendingUp className="w-3 h-3" /> LONG
              </button>
              <button
                onClick={() => { setDirectionFilter("SHORT"); setPage(1); }}
                className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1 ${directionFilter === "SHORT" ? "bg-rose-950 text-rose-400 border border-rose-500/30" : "text-slate-400 hover:text-rose-400"}`}
              >
                <TrendingDown className="w-3 h-3" /> SHORT
              </button>
            </div>

            {/* Horizon Filter */}
            <select
              value={horizonFilter}
              onChange={(e) => { setHorizonFilter(e.target.value); setPage(1); }}
              className="bg-slate-950/80 border border-slate-800 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 font-bold focus:outline-none focus:border-cyan-500/50 cursor-pointer"
            >
              <option value="ALL">All Horizons (9 Timeframes)</option>
              {horizons.map((h) => (
                <option key={h} value={h}>Horizon: {h}</option>
              ))}
            </select>

            {/* Grade Filter */}
            <select
              value={gradeFilter}
              onChange={(e) => { setGradeFilter(e.target.value); setPage(1); }}
              className="bg-slate-950/80 border border-slate-800 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 font-bold focus:outline-none focus:border-cyan-500/50 cursor-pointer"
            >
              <option value="ALL">All Quality Grades</option>
              <option value="A_PLUS">Grade A+ Only</option>
              <option value="A">Grade A</option>
              <option value="B">Grade B</option>
            </select>
          </div>

          <div className="text-xs text-slate-400">
            Showing <strong className="text-slate-200">{filteredSignals.length}</strong> of <strong className="text-slate-200">{v16Signals.length}</strong> Audited V16 Signals
          </div>
        </div>
      </div>

      {/* ========================================================= */}
      {/* 4. MAIN AUDIT DISPLAY: TABLE OR CARDS */}
      {/* ========================================================= */}
      {isLoading ? (
        <div className="p-16 rounded-2xl border border-slate-800/80 bg-slate-900/40 text-center flex flex-col items-center justify-center gap-3 font-mono">
          <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
          <span className="text-sm font-bold text-slate-300">Loading Authoritative V16 Signals Audit Ledger...</span>
        </div>
      ) : filteredSignals.length === 0 ? (
        <div className="p-16 rounded-2xl border border-dashed border-slate-800/80 bg-slate-900/30 text-center flex flex-col items-center justify-center gap-3 font-mono">
          <ShieldCheck className="w-8 h-8 text-slate-600 animate-pulse" />
          <h3 className="text-base font-bold text-slate-300">No V16 Signals Match Filter Criteria</h3>
          <p className="text-xs text-slate-400 max-w-md">
            This audit ledger strictly records signals generated by the Quant Edge V16 intelligence engine with positive Net EV and verified risk geometry.
          </p>
          <button
            onClick={() => {
              setSearch("");
              setStatusFilter("ALL");
              setDirectionFilter("ALL");
              setHorizonFilter("ALL");
              setGradeFilter("ALL");
              setPage(1);
            }}
            className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700 hover:border-cyan-500 text-xs text-cyan-300 font-bold transition-all shadow-sm"
          >
            Reset Filters
          </button>
        </div>
      ) : viewMode === "CARDS" ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            {paginatedSignals.map((signal) => (
              <V16SignalCard
                key={signal.immutable?.signal_id}
                signal={signal}
                onSelect={(s) => setSelectedSignal(s)}
                isSelected={selectedSignal?.immutable?.signal_id === signal.immutable?.signal_id}
              />
            ))}
          </div>
        </div>
      ) : (
        /* AUDIT TABLE VIEW */
        <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-slate-800/80 bg-slate-950/70 text-[10px] text-slate-400 uppercase tracking-wider font-bold">
                  <th className="py-3 px-4">Date / Signal ID</th>
                  <th className="py-3 px-4">Pair &amp; Direction</th>
                  <th className="py-3 px-3">Horizon</th>
                  <th className="py-3 px-3">Grade</th>
                  <th className="py-3 px-4">Entry / Live</th>
                  <th className="py-3 px-4">Stop Loss</th>
                  <th className="py-3 px-4">Target (TP1)</th>
                  <th className="py-3 px-3 text-right">Net EV</th>
                  <th className="py-3 px-3 text-right">Win Prob</th>
                  <th className="py-3 px-3 text-right">R:R</th>
                  <th className="py-3 px-4 text-center">Status / Outcome</th>
                  <th className="py-3 px-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {paginatedSignals.map((s) => {
                  const imm = s.immutable;
                  const dyn = s.dynamic;
                  const isLong = (imm.direction || "").toUpperCase() === "LONG";
                  const gradeBadge = getGradeBadge(imm.grade);
                  const st = getSignalStatus(s);

                  const entryP = imm.entry_price_initial || 0;
                  const currP = dyn?.current_price || entryP;
                  const slP = dyn?.current_sl || imm.sl_initial || 0;
                  const tp1P = imm.tp1_initial || 0;
                  const isBeLocked = dyn?.is_tp1_locked || dyn?.locked_sl !== null || dyn?.trailing_sl !== null;

                  return (
                    <tr
                      key={imm.signal_id}
                      onClick={() => setSelectedSignal(s)}
                      className="hover:bg-slate-800/50 transition-colors cursor-pointer group"
                    >
                      {/* Timestamp & ID */}
                      <td className="py-3 px-4">
                        <div className="font-bold text-slate-200">{imm.signal_generated_at?.substring(0, 16) || "Recent"}</div>
                        <div className="text-[10px] text-slate-400 truncate max-w-[120px]" title={imm.signal_id}>
                          {imm.signal_id}
                        </div>
                      </td>

                      {/* Pair & Direction */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className="font-black text-white group-hover:text-cyan-300 transition-colors">
                            {imm.symbol}
                          </span>
                          <span
                            className={`px-1.5 py-0.2 rounded text-[10px] font-bold border ${
                              isLong
                                ? "bg-emerald-950/70 text-emerald-300 border-emerald-500/40"
                                : "bg-rose-950/70 text-rose-300 border-rose-500/40"
                            }`}
                          >
                            {imm.direction}
                          </span>
                        </div>
                        <div className="text-[10px] text-slate-400 truncate max-w-[130px]" title={imm.trade_thesis_id}>
                          {imm.trade_thesis_id}
                        </div>
                      </td>

                      {/* Horizon */}
                      <td className="py-3 px-3">
                        <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-800/90 text-cyan-300 border border-cyan-500/30">
                          {imm.horizon}
                        </span>
                      </td>

                      {/* Grade */}
                      <td className="py-3 px-3">
                        <span className={`px-2 py-0.5 rounded-md text-[10px] font-black border ${gradeBadge.bg} ${gradeBadge.border} ${gradeBadge.text}`}>
                          {imm.grade}
                        </span>
                      </td>

                      {/* Entry & Live */}
                      <td className="py-3 px-4">
                        <div className="font-bold text-slate-200">{formatPrice(entryP)}</div>
                        {currP !== entryP && (
                          <div className={`text-[10px] font-bold ${dyn?.unrealized_net_pnl_pct && dyn.unrealized_net_pnl_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                            {formatPrice(currP)} ({formatPercent(dyn?.unrealized_net_pnl_pct)})
                          </div>
                        )}
                      </td>

                      {/* Stop Loss */}
                      <td className="py-3 px-4">
                        {(() => {
                          const slSignedPct = entryP > 0 ? ((isLong ? (slP - entryP) : (entryP - slP)) / entryP) * 100 : 0;
                          const isSlInProfit = entryP > 0 && slP > 0 && (isLong ? slP >= entryP : slP <= entryP);
                          return (
                            <>
                              <div className={`flex items-center gap-1 font-bold ${isSlInProfit ? "text-emerald-400" : "text-rose-400"}`}>
                                {(isBeLocked || isSlInProfit) && <Lock className="w-3 h-3 text-amber-300" />}
                                <span>{formatPrice(slP)}</span>
                              </div>
                              <div className={`text-[10px] ${isSlInProfit ? "text-emerald-400/90" : "text-slate-400"}`}>
                                {isSlInProfit ? "+" : "-"}{Math.abs(slSignedPct).toFixed(1)}%
                              </div>
                            </>
                          );
                        })()}
                      </td>

                      {/* Target TP1 */}
                      <td className="py-3 px-4">
                        <div className="font-bold text-emerald-400">{formatPrice(tp1P)}</div>
                        <div className="text-[10px] text-slate-400">
                          +{entryP > 0 ? ((Math.abs(tp1P - entryP) / entryP) * 100).toFixed(1) : 0}%
                        </div>
                      </td>

                      {/* Net EV */}
                      <td className="py-3 px-3 text-right">
                        <span className={`font-black ${imm.expected_net_return > 0 ? "text-cyan-300" : "text-rose-400"}`}>
                          {formatPercent(imm.expected_net_return)}
                        </span>
                      </td>

                      {/* Win Prob */}
                      <td className="py-3 px-3 text-right">
                        <span className="font-bold text-emerald-400">
                          {formatProbability(imm.p_tp1)}
                        </span>
                      </td>

                      {/* Risk Reward */}
                      <td className="py-3 px-3 text-right">
                        <span className="font-bold text-amber-300">
                          1:{imm.risk_reward ? imm.risk_reward.toFixed(2) : "2.00"}
                        </span>
                      </td>

                      {/* Status / Outcome */}
                      <td className="py-3 px-4 text-center">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border ${
                            st === "WON"
                              ? "bg-emerald-950/70 text-emerald-300 border-emerald-500/50"
                              : st === "LOST"
                              ? "bg-rose-950/70 text-rose-300 border-rose-500/50"
                              : st === "BREAKEVEN"
                              ? "bg-amber-950/70 text-amber-300 border-amber-500/50"
                              : st === "EXPIRED"
                              ? "bg-slate-800 text-slate-400 border-slate-700"
                              : "bg-cyan-950/70 text-cyan-300 border-cyan-500/40 animate-pulse"
                          }`}
                        >
                          {dyn?.outcome_label || st}
                        </span>
                      </td>

                      {/* Action */}
                      <td className="py-3 px-3 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedSignal(s);
                          }}
                          className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-cyan-950 border border-slate-700 hover:border-cyan-500/50 text-slate-300 hover:text-cyan-300 font-bold transition-all text-[11px]"
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* 5. PAGINATION CONTROLS */}
      {/* ========================================================= */}
      {filteredSignals.length > pageSize && (
        <div className="p-3 rounded-xl border border-slate-800/80 bg-slate-950/60 flex items-center justify-between text-xs font-mono">
          <div className="text-slate-400">
            Page <strong className="text-slate-200">{page}</strong> of <strong className="text-slate-200">{totalPages}</strong> ({filteredSignals.length} total qualified records)
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>

            <span className="px-3 py-1 rounded-lg bg-slate-900 text-cyan-300 font-bold border border-slate-800">
              {page}
            </span>

            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Forensic Signal Detail Modal */}
      <V16SignalDetailModal
        signal={selectedSignal}
        onClose={() => setSelectedSignal(null)}
      />
    </div>
  );
}

