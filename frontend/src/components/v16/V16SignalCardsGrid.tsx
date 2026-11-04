"use client";

import React, { useState, useMemo, useEffect } from "react";
import { V16SignalEnvelope } from "@/types/v16";
import V16SignalCard from "@/components/v16/V16SignalCard";
import { formatPercent, formatProbability } from "@/lib/utils/v16";
import {
  Search,
  Filter,
  ArrowUpDown,
  Sparkles,
  ShieldCheck,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Layers,
  Zap,
  SlidersHorizontal
} from "lucide-react";

interface Props {
  signals: V16SignalEnvelope[];
  onSelectSignal: (signal: V16SignalEnvelope) => void;
  selectedSignalId?: string;
}

export default function V16SignalCardsGrid({
  signals,
  onSelectSignal,
  selectedSignalId,
}: Props) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ACTIVE");
  const [directionFilter, setDirectionFilter] = useState<string>("ALL");
  const [horizonFilter, setHorizonFilter] = useState<string>("ALL");
  const [gradeFilter, setGradeFilter] = useState<string>("ALL");
  const [strictV16Only, setStrictV16Only] = useState<boolean>(true);
  const [minEvFilter, setMinEvFilter] = useState<number>(0);
  const [sortField, setSortField] = useState<string>("net_ev");
  const [sortAsc, setSortAsc] = useState<boolean>(false);
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(12);

  // Available unique horizons from real data
  const horizons = useMemo(() => {
    const set = new Set<string>();
    signals.forEach((s) => {
      if (s.immutable?.horizon) set.add(s.immutable.horizon);
    });
    const standardOrder = ["5M", "15M", "1H", "4H", "12H", "24H", "7D", "15D", "1M"];
    return standardOrder.filter((h) => set.has(h)).concat(Array.from(set).filter((h) => !standardOrder.includes(h)));
  }, [signals]);

  // Deterministic signal status classifier
  const getSignalCategory = (item: V16SignalEnvelope): "ACTIVE" | "WON" | "LOST" | "BREAKEVEN" | "EXPIRED" => {
    const st = (item.dynamic?.status || item.immutable?.status || "").toUpperCase();
    const out = (item.dynamic?.outcome_label || "").toUpperCase();

    if (st.includes("WON") || out.includes("WON") || out.includes("TP1") || out.includes("TP2") || out.includes("TP3") || st.includes("PROFIT")) {
      return "WON";
    }
    if (st.includes("LOST") || out.includes("LOST") || st.includes("STOP") || out.includes("STOP")) {
      return "LOST";
    }
    if (st.includes("BREAKEVEN") || st.includes("BE_") || st.includes("SOFT_BE") || out.includes("BREAKEVEN") || out.includes("BE") || st.includes("TIER0_BE")) {
      return "BREAKEVEN";
    }
    if (st.includes("EXP") || out.includes("EXP") || st.includes("STAGNATION") || out.includes("TIMEOUT")) {
      return "EXPIRED";
    }
    return "ACTIVE";
  };

  // V16 Qualification Rule Check
  // 1. Expected Net Return strictly positive (EV_net > 0)
  // 2. Grade A+, A, or B
  // 3. Mathematical price geometry: SL < Entry < TP1 for Long, SL > Entry > TP1 for Short
  const isV16RuleQualified = (item: V16SignalEnvelope): boolean => {
    const imm = item.immutable;
    if (!imm) return false;
    
    // Rule 1: EVnet > 0
    if (imm.expected_net_return <= 0) return false;

    // Rule 2: Grade must be qualified (A+, A, B)
    const g = (imm.grade || "").toUpperCase();
    const isGradeOk = g.includes("A+") || g.includes("GRADE A") || g.includes("GRADE B") || g.includes("A") || g.includes("B");
    if (!isGradeOk) return false;

    // Rule 3: Valid price structure
    const entry = imm.entry_price_initial || 0;
    const sl = imm.sl_initial || 0;
    const tp1 = imm.tp1_initial || 0;
    const isLong = (imm.direction || "").toUpperCase() === "LONG";

    if (entry <= 0 || sl <= 0 || tp1 <= 0) return false;
    if (isLong && !(sl < entry && entry < tp1)) return false;
    if (!isLong && !(sl > entry && entry > tp1)) return false;

    return true;
  };

  // Pre-filter for V16 qualified signals
  const qualifiedSignalsPool = useMemo(() => {
    if (!strictV16Only) return signals;
    return signals.filter(isV16RuleQualified);
  }, [signals, strictV16Only]);

  // Counts by status among qualified signals
  const counts = useMemo(() => {
    let active = 0;
    let won = 0;
    let lost = 0;
    let breakevenOrExpired = 0;

    qualifiedSignalsPool.forEach((s) => {
      const cat = getSignalCategory(s);
      if (cat === "WON") won++;
      else if (cat === "LOST") lost++;
      else if (cat === "BREAKEVEN" || cat === "EXPIRED") breakevenOrExpired++;
      else active++;
    });

    return { active, won, lost, breakevenOrExpired, total: qualifiedSignalsPool.length };
  }, [qualifiedSignalsPool]);

  // Filtered & Sorted signals
  const filteredSignals = useMemo(() => {
    return qualifiedSignalsPool
      .filter((item) => {
        const sym = item.immutable.symbol.toUpperCase();
        const tid = (item.immutable.trade_thesis_id || "").toUpperCase();
        const sid = (item.immutable.signal_id || "").toUpperCase();
        const sQuery = search.trim().toUpperCase();

        if (sQuery && !sym.includes(sQuery) && !tid.includes(sQuery) && !sid.includes(sQuery)) {
          return false;
        }

        // Status Filter
        if (statusFilter !== "ALL") {
          const cat = getSignalCategory(item);
          if (statusFilter === "ACTIVE" && cat !== "ACTIVE") return false;
          if (statusFilter === "WON" && cat !== "WON") return false;
          if (statusFilter === "LOST" && cat !== "LOST") return false;
          if (statusFilter === "BREAKEVEN_EXPIRED" && cat !== "BREAKEVEN" && cat !== "EXPIRED") return false;
        }

        // Direction Filter
        if (directionFilter !== "ALL" && item.immutable.direction.toUpperCase() !== directionFilter) {
          return false;
        }

        // Horizon Filter
        if (horizonFilter !== "ALL" && item.immutable.horizon !== horizonFilter) {
          return false;
        }

        // Grade Filter
        if (gradeFilter !== "ALL") {
          const g = (item.immutable.grade || "").toUpperCase();
          if (gradeFilter === "A_PLUS" && !g.includes("A+")) return false;
          if (gradeFilter === "A_OR_A_PLUS" && !g.includes("A")) return false;
        }

        // Minimum Net EV
        if (item.immutable.expected_net_return < minEvFilter) {
          return false;
        }

        return true;
      })
      .sort((a, b) => {
        let valA = 0;
        let valB = 0;
        if (sortField === "net_ev") {
          valA = a.immutable.expected_net_return;
          valB = b.immutable.expected_net_return;
        } else if (sortField === "p_tp1") {
          valA = a.immutable.p_tp1;
          valB = b.immutable.p_tp1;
        } else if (sortField === "symbol") {
          return sortAsc
            ? a.immutable.symbol.localeCompare(b.immutable.symbol)
            : b.immutable.symbol.localeCompare(a.immutable.symbol);
        } else if (sortField === "risk_reward") {
          valA = a.immutable.risk_reward;
          valB = b.immutable.risk_reward;
        } else if (sortField === "score") {
          valA = a.immutable.signal_score || 0;
          valB = b.immutable.signal_score || 0;
        }
        return sortAsc ? valA - valB : valB - valA;
      });
  }, [qualifiedSignalsPool, search, statusFilter, directionFilter, horizonFilter, gradeFilter, minEvFilter, sortField, sortAsc]);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, directionFilter, horizonFilter, gradeFilter, strictV16Only, minEvFilter, pageSize]);

  const totalPages = Math.max(1, Math.ceil(filteredSignals.length / pageSize));
  const paginatedSignals = useMemo(() => {
    return filteredSignals.slice((page - 1) * pageSize, page * pageSize);
  }, [filteredSignals, page, pageSize]);

  // Aggregate metrics of displayed cards
  const { avgNetEv, avgPtp1, avgRr } = useMemo(() => {
    if (filteredSignals.length === 0) return { avgNetEv: 0, avgPtp1: 0, avgRr: 0 };
    const sumEv = filteredSignals.reduce((acc, s) => acc + (s.immutable.expected_net_return || 0), 0);
    const sumP = filteredSignals.reduce((acc, s) => {
      const p = s.immutable.p_tp1 || 0;
      return acc + (p > 1.0 ? p / 100.0 : p);
    }, 0);
    const sumRr = filteredSignals.reduce((acc, s) => acc + (s.immutable.risk_reward || 0), 0);

    return {
      avgNetEv: sumEv / filteredSignals.length,
      avgPtp1: (sumP / filteredSignals.length) * 100,
      avgRr: sumRr / filteredSignals.length,
    };
  }, [filteredSignals]);

  return (
    <div className="space-y-4">
      {/* ========================================================= */}
      {/* 1. CARDS TOOLBAR & STATUS TABS */}
      {/* ========================================================= */}
      <div className="p-4 rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl shadow-lg flex flex-col gap-3.5">
        {/* Status Filter Tab Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-slate-900/90 border border-slate-800">
            <button
              onClick={() => setStatusFilter("ACTIVE")}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "ACTIVE"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>ACTIVE QUALIFIED</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-cyan-300">
                {counts.active}
              </span>
            </button>

            <button
              onClick={() => setStatusFilter("WON")}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "WON"
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>TP HIT (WON)</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-emerald-300">
                {counts.won}
              </span>
            </button>

            <button
              onClick={() => setStatusFilter("BREAKEVEN_EXPIRED")}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "BREAKEVEN_EXPIRED"
                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>BE / EXPIRED</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-amber-300">
                {counts.breakevenOrExpired}
              </span>
            </button>

            <button
              onClick={() => setStatusFilter("LOST")}
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
              onClick={() => setStatusFilter("ALL")}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "ALL"
                  ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>ALL SIGNALS</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-indigo-300">
                {counts.total}
              </span>
            </button>
          </div>

          {/* Strict V16 Rule Hurdle Toggle */}
          <button
            onClick={() => setStrictV16Only(!strictV16Only)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-mono font-bold border transition-all ${
              strictV16Only
                ? "bg-emerald-950/80 border-emerald-500/50 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.2)]"
                : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
            }`}
          >
            <ShieldCheck className={`w-3.5 h-3.5 ${strictV16Only ? "text-emerald-400" : "text-slate-500"}`} />
            <span>Strict V16 Hurdle (EVnet &gt; 0%)</span>
          </button>
        </div>

        {/* Search, Direction, Horizon, Grade, and Sorting Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-800/60">
          <div className="flex flex-wrap items-center gap-2 flex-1">
            {/* Search Input */}
            <div className="relative min-w-[180px] max-w-xs flex-1">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search symbol, thesis..."
                className="w-full bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 font-mono focus:outline-none focus:border-cyan-500/50 transition-colors"
              />
            </div>

            {/* Direction Filter */}
            <div className="flex items-center gap-1 p-0.5 rounded-lg bg-slate-950/80 border border-slate-800 text-[11px] font-mono font-bold">
              <button
                onClick={() => setDirectionFilter("ALL")}
                className={`px-2.5 py-1 rounded-md transition-all ${directionFilter === "ALL" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"}`}
              >
                ALL
              </button>
              <button
                onClick={() => setDirectionFilter("LONG")}
                className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1 ${directionFilter === "LONG" ? "bg-emerald-950 text-emerald-400 border border-emerald-500/30" : "text-slate-400 hover:text-emerald-400"}`}
              >
                <TrendingUp className="w-3 h-3" /> LONG
              </button>
              <button
                onClick={() => setDirectionFilter("SHORT")}
                className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1 ${directionFilter === "SHORT" ? "bg-rose-950 text-rose-400 border border-rose-500/30" : "text-slate-400 hover:text-rose-400"}`}
              >
                <TrendingDown className="w-3 h-3" /> SHORT
              </button>
            </div>

            {/* Quality Grade Filter */}
            <select
              value={gradeFilter}
              onChange={(e) => setGradeFilter(e.target.value)}
              className="bg-slate-950/80 border border-slate-800 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 font-mono font-bold focus:outline-none focus:border-cyan-500/50 cursor-pointer"
            >
              <option value="ALL">All Grades (A+, A, B)</option>
              <option value="A_PLUS">Grade A+ Only</option>
              <option value="A_OR_A_PLUS">Grade A &amp; A+</option>
            </select>

            {/* Horizon Filter Dropdown or Pills */}
            <select
              value={horizonFilter}
              onChange={(e) => setHorizonFilter(e.target.value)}
              className="bg-slate-950/80 border border-slate-800 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 font-mono font-bold focus:outline-none focus:border-cyan-500/50 cursor-pointer"
            >
              <option value="ALL">All Horizons (9 Timeframes)</option>
              {horizons.map((h) => (
                <option key={h} value={h}>
                  Horizon: {h}
                </option>
              ))}
            </select>
          </div>

          {/* Sort Dropdown & Page Size */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 bg-slate-950/80 border border-slate-800 rounded-xl px-2.5 py-1.5 text-xs font-mono text-slate-300">
              <ArrowUpDown className="w-3 h-3 text-cyan-400" />
              <select
                value={sortField}
                onChange={(e) => setSortField(e.target.value)}
                className="bg-transparent border-none text-slate-300 focus:outline-none cursor-pointer font-bold"
              >
                <option value="net_ev">Sort: Highest Net EV</option>
                <option value="p_tp1">Sort: Win Probability</option>
                <option value="risk_reward">Sort: Risk:Reward</option>
                <option value="score">Sort: Model Score</option>
                <option value="symbol">Sort: Symbol A-Z</option>
              </select>
            </div>

            <button
              onClick={() => setSortAsc(!sortAsc)}
              title={sortAsc ? "Ascending order" : "Descending order"}
              className="p-1.5 rounded-xl bg-slate-950/80 border border-slate-800 text-slate-400 hover:text-cyan-300 transition-colors"
            >
              {sortAsc ? <TrendingUp className="w-4 h-4 text-cyan-400" /> : <TrendingDown className="w-4 h-4 text-cyan-400" />}
            </button>
          </div>
        </div>

        {/* Live Filter Summary Banner */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 rounded-xl bg-slate-950/50 border border-slate-800/60 text-xs font-mono text-slate-400">
          <div className="flex items-center gap-2">
            <span className="text-slate-300 font-bold">
              Showing {filteredSignals.length} of {qualifiedSignalsPool.length} V16 Qualified Cards
            </span>
            {strictV16Only && (
              <span className="px-2 py-0.5 rounded-md bg-emerald-950/70 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold">
                EVnet &gt; 0% Verified
              </span>
            )}
          </div>

          {filteredSignals.length > 0 && (
            <div className="flex items-center gap-4 text-[11px]">
              <span>
                Avg Net EV: <strong className="text-cyan-300">+{avgNetEv.toFixed(2)}%</strong>
              </span>
              <span>•</span>
              <span>
                Avg Win Prob: <strong className="text-emerald-400">{avgPtp1.toFixed(1)}%</strong>
              </span>
              <span>•</span>
              <span>
                Avg R:R: <strong className="text-amber-300">1:{avgRr.toFixed(2)}</strong>
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ========================================================= */}
      {/* 2. RESPONSIVE CARDS GRID */}
      {/* ========================================================= */}
      {paginatedSignals.length === 0 ? (
        <div className="p-12 rounded-2xl border border-dashed border-slate-800/80 bg-slate-900/30 text-center flex flex-col items-center justify-center gap-3 font-mono">
          <ShieldCheck className="w-8 h-8 text-slate-600 animate-pulse" />
          <h3 className="text-base font-bold text-slate-300">No V16 Signals Match Current Filter Criteria</h3>
          <p className="text-xs text-slate-400 max-w-md">
            All signals passing the strict V16 hurdle must maintain positive expected net return (EVnet &gt; 0%) after full friction deductions, valid price geometry, and grade qualification.
          </p>
          <button
            onClick={() => {
              setSearch("");
              setStatusFilter("ALL");
              setDirectionFilter("ALL");
              setHorizonFilter("ALL");
              setGradeFilter("ALL");
              setStrictV16Only(false);
            }}
            className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700 hover:border-cyan-500 text-xs text-cyan-300 font-bold transition-all shadow-sm"
          >
            Reset All Filters
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {paginatedSignals.map((signal) => (
            <V16SignalCard
              key={signal.immutable?.signal_id || signal.dynamic?.signal_id}
              signal={signal}
              onSelect={onSelectSignal}
              isSelected={selectedSignalId === signal.immutable?.signal_id}
            />
          ))}
        </div>
      )}

      {/* ========================================================= */}
      {/* 3. PAGINATION CONTROLS */}
      {/* ========================================================= */}
      {filteredSignals.length > pageSize && (
        <div className="p-3 rounded-xl border border-slate-800/80 bg-slate-950/60 flex items-center justify-between text-xs font-mono">
          <div className="text-slate-400">
            Page <strong className="text-slate-200">{page}</strong> of <strong className="text-slate-200">{totalPages}</strong> ({filteredSignals.length} total qualified cards)
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
    </div>
  );
}
