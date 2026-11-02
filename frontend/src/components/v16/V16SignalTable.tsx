"use client";

import React, { useState, useMemo, useEffect } from "react";
import { V16SignalEnvelope } from "@/types/v16";
import { formatPrice, formatPercent, formatProbability, getGradeBadge } from "@/lib/utils/v16";
import { Search, ArrowUpDown, ChevronRight, ChevronLeft, Layers, ShieldCheck, CheckCircle2, SlidersHorizontal, RefreshCw } from "lucide-react";

interface Props {
  signals: V16SignalEnvelope[];
  onSelectSignal: (signal: V16SignalEnvelope) => void;
  selectedSignalId?: string;
}

export default function V16SignalTable({
  signals,
  onSelectSignal,
  selectedSignalId,
}: Props) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ACTIVE");
  const [directionFilter, setDirectionFilter] = useState<string>("ALL");
  const [horizonFilter, setHorizonFilter] = useState<string>("ALL");
  const [minEvFilter, setMinEvFilter] = useState<number>(0);
  const [sortField, setSortField] = useState<string>("net_ev");
  const [sortAsc, setSortAsc] = useState<boolean>(false);
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(20);

  // Available unique horizons from real data
  const horizons = useMemo(() => {
    const set = new Set<string>();
    signals.forEach((s) => {
      if (s.immutable.horizon) set.add(s.immutable.horizon);
    });
    return Array.from(set);
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
    if (st.includes("EXP") || out.includes("EXP") || st.includes("STAGNATION") || out.includes("STAGNATION") || st.includes("TIMEOUT")) {
      return "EXPIRED";
    }
    return "ACTIVE";
  };

  // Counts by status
  const counts = useMemo(() => {
    let active = 0;
    let won = 0;
    let lost = 0;
    let breakevenOrExpired = 0;

    signals.forEach((s) => {
      const cat = getSignalCategory(s);
      if (cat === "WON") won++;
      else if (cat === "LOST") lost++;
      else if (cat === "BREAKEVEN" || cat === "EXPIRED") breakevenOrExpired++;
      else active++;
    });

    return { active, won, lost, breakevenOrExpired, total: signals.length };
  }, [signals]);

  // Filtering & Sorting
  const filteredSignals = useMemo(() => {
    return signals
      .filter((item) => {
        const sym = item.immutable.symbol.toUpperCase();
        const tid = item.immutable.trade_thesis_id.toUpperCase();
        const sid = item.immutable.signal_id.toUpperCase();
        const sQuery = search.toUpperCase();

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
        }
        return sortAsc ? valA - valB : valB - valA;
      });
  }, [signals, search, statusFilter, directionFilter, horizonFilter, minEvFilter, sortField, sortAsc]);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, directionFilter, horizonFilter, minEvFilter, pageSize]);

  const totalPages = Math.max(1, Math.ceil(filteredSignals.length / pageSize));
  const paginatedSignals = useMemo(() => {
    return filteredSignals.slice((page - 1) * pageSize, page * pageSize);
  }, [filteredSignals, page, pageSize]);

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  };

  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col">
      {/* Table Toolbar & Status Tabs */}
      <div className="p-4 border-b border-slate-800/80 bg-slate-950/60 flex flex-col gap-3">
        {/* Status Filter Tab Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-slate-900/80 border border-slate-800">
            <button
              onClick={() => setStatusFilter("ACTIVE")}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "ACTIVE"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>ACTIVE SETUPS</span>
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
              onClick={() => setStatusFilter("ALL")}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
                statusFilter === "ALL"
                  ? "bg-slate-800 text-white border border-slate-700 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>ALL SIGNALS</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-slate-300">
                {counts.total}
              </span>
            </button>
          </div>

          {/* Qualified Count Indicator */}
          <div className="text-xs font-mono text-slate-400 flex items-center gap-1.5">
            <span>Showing:</span>
            <strong className="text-cyan-300">{filteredSignals.length}</strong>
            <span>of</span>
            <strong className="text-white">{signals.length}</strong>
            <span className="text-[10px] text-emerald-400 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-500/30 hidden sm:inline">
              EV &gt; 0% Verified
            </span>
          </div>
        </div>

        {/* Filter Controls Row */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {/* Search Input */}
          <div className="relative flex-1 min-w-[200px] max-w-[340px]">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search Symbol / Thesis / ID..."
              className="w-full bg-slate-900/90 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/30 font-mono transition-all"
            />
          </div>

          {/* Direction Filter */}
          <select
            value={directionFilter}
            onChange={(e) => setDirectionFilter(e.target.value)}
            className="bg-slate-900/90 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-300 font-mono focus:outline-none focus:border-cyan-500/60 transition-all"
          >
            <option value="ALL">Direction: ALL</option>
            <option value="LONG">LONG</option>
            <option value="SHORT">SHORT</option>
          </select>

          {/* Horizon Filter */}
          <select
            value={horizonFilter}
            onChange={(e) => setHorizonFilter(e.target.value)}
            className="bg-slate-900/90 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-300 font-mono focus:outline-none focus:border-cyan-500/60 transition-all"
          >
            <option value="ALL">Horizon: ALL</option>
            {horizons.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>

          {/* Min EV Filter */}
          <select
            value={minEvFilter}
            onChange={(e) => setMinEvFilter(Number(e.target.value))}
            className="bg-slate-900/90 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-300 font-mono focus:outline-none focus:border-cyan-500/60 transition-all"
          >
            <option value={0}>Min Net EV: &gt; 0% (All EV+)</option>
            <option value={0.25}>Min Net EV: &ge; +0.25% (Grade B)</option>
            <option value={0.5}>Min Net EV: &ge; +0.50% (Grade A)</option>
            <option value={1.0}>Min Net EV: &ge; +1.00% (Grade A+)</option>
          </select>
        </div>
      </div>

      {/* Responsive Table Container */}
      <div className="overflow-x-auto touch-scroll">
        <table className="w-full text-left border-collapse font-mono text-xs">
          <thead>
            <tr className="border-b border-slate-800/80 bg-slate-950/90 text-[11px] text-slate-400 uppercase tracking-wider select-none">
              <th className="py-3 px-3.5">Status</th>
              <th className="py-3 px-3.5 cursor-pointer hover:text-white" onClick={() => handleSort("symbol")}>
                <div className="flex items-center gap-1.5">
                  <span>Symbol / Horizon</span>
                  <ArrowUpDown className="w-3 h-3 text-slate-500" />
                </div>
              </th>
              <th className="py-3 px-3.5">Direction</th>
              <th className="py-3 px-3.5">Entry Zone</th>
              <th className="py-3 px-3.5">Stop Loss</th>
              <th className="py-3 px-3.5">Target 1</th>
              <th className="py-3 px-3.5 cursor-pointer hover:text-white" onClick={() => handleSort("p_tp1")}>
                <div className="flex items-center gap-1.5">
                  <span>P(TP1)</span>
                  <ArrowUpDown className="w-3 h-3 text-slate-500" />
                </div>
              </th>
              <th className="py-3 px-3.5">P(SL)</th>
              <th className="py-3 px-3.5 cursor-pointer hover:text-white" onClick={() => handleSort("net_ev")}>
                <div className="flex items-center gap-1.5">
                  <span>Net EV</span>
                  <ArrowUpDown className="w-3 h-3 text-slate-500" />
                </div>
              </th>
              <th className="py-3 px-3.5 cursor-pointer hover:text-white" onClick={() => handleSort("risk_reward")}>
                <div className="flex items-center gap-1.5">
                  <span>R:R</span>
                  <ArrowUpDown className="w-3 h-3 text-slate-500" />
                </div>
              </th>
              <th className="py-3 px-3.5">Grade</th>
              <th className="py-3 px-3.5">Trade Thesis</th>
              <th className="py-3 px-3.5 text-right">Inspect</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {filteredSignals.length === 0 ? (
              <tr>
                <td colSpan={13} className="py-12 text-center text-slate-500 font-mono text-xs">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <ShieldCheck className="w-8 h-8 text-slate-600" />
                    <span className="text-slate-400 font-bold">No signals meet the selected criteria.</span>
                    <span className="text-[11px] text-slate-500">
                      V16 Capital Protection Guard: only signals with positive expected net return (EVnet &gt; 0%) are permitted.
                    </span>
                  </div>
                </td>
              </tr>
            ) : (
              paginatedSignals.map((item) => {
                const isSelected = selectedSignalId === item.immutable.signal_id;
                const isLong = item.immutable.direction.toUpperCase() === "LONG";
                const cat = getSignalCategory(item);
                const gradeBadge = getGradeBadge(item.immutable.grade);

                return (
                  <tr
                    key={item.immutable.signal_id}
                    onClick={() => onSelectSignal(item)}
                    className={`cursor-pointer transition-all duration-150 ${
                      isSelected
                        ? "bg-cyan-950/30 border-l-2 border-cyan-400"
                        : "hover:bg-slate-800/40"
                    }`}
                  >
                    {/* Status */}
                    <td className="py-3 px-3.5 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        {cat === "WON" ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950/70 text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
                            <CheckCircle2 className="w-2.5 h-2.5" /> TP HIT
                          </span>
                        ) : cat === "LOST" ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-950/70 text-rose-300 border border-rose-500/30">
                            STOPPED
                          </span>
                        ) : cat === "BREAKEVEN" ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-950/70 text-cyan-300 border border-cyan-500/30">
                            BREAKEVEN
                          </span>
                        ) : cat === "EXPIRED" ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-800/80 text-slate-400 border border-slate-700">
                            EXPIRED
                          </span>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <span className="relative flex h-2 w-2">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
                            </span>
                            <span className="text-[11px] text-emerald-400 font-bold">
                              ACTIVE
                            </span>
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Symbol / Horizon */}
                    <td className="py-3 px-3.5 whitespace-nowrap">
                      <div className="font-bold text-white text-sm">{item.immutable.symbol}</div>
                      <div className="text-[10px] text-cyan-400/90 font-bold">{item.immutable.horizon}</div>
                    </td>

                    {/* Direction */}
                    <td className="py-3 px-3.5 whitespace-nowrap">
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-[10px] font-black border ${
                          isLong
                            ? "bg-emerald-950/60 text-emerald-300 border-emerald-500/30 shadow-[0_0_8px_rgba(16,185,129,0.2)]"
                            : "bg-rose-950/60 text-rose-300 border-rose-500/30 shadow-[0_0_8px_rgba(244,63,94,0.2)]"
                        }`}
                      >
                        {item.immutable.direction}
                      </span>
                    </td>

                    {/* Entry */}
                    <td className="py-3 px-3.5 whitespace-nowrap text-slate-200 font-bold">
                      {formatPrice(item.immutable.entry_price_initial)}
                    </td>

                    {/* SL */}
                    <td className="py-3 px-3.5 whitespace-nowrap text-rose-400">
                      {formatPrice(item.immutable.sl_initial)}
                    </td>

                    {/* TP1 */}
                    <td className="py-3 px-3.5 whitespace-nowrap text-emerald-400 font-bold">
                      {formatPrice(item.immutable.tp1_initial)}
                    </td>

                    {/* Calibrated P(TP1) */}
                    <td className="py-3 px-3.5 whitespace-nowrap">
                      <span className="font-bold text-indigo-300 bg-indigo-950/40 px-2 py-0.5 rounded border border-indigo-500/20">
                        {formatProbability(item.immutable.p_tp1)}
                      </span>
                    </td>

                    {/* P(SL) */}
                    <td className="py-3 px-3.5 whitespace-nowrap text-slate-400">
                      {formatProbability(item.immutable.p_sl)}
                    </td>

                    {/* Net EV */}
                    <td className="py-3 px-3.5 whitespace-nowrap">
                      <span
                        className={`font-black text-xs px-2 py-0.5 rounded ${
                          item.immutable.expected_net_return > 0
                            ? "text-emerald-300 bg-emerald-950/40 border border-emerald-500/30"
                            : "text-rose-400 bg-rose-950/40 border border-rose-500/30"
                        }`}
                      >
                        {formatPercent(item.immutable.expected_net_return)}
                      </span>
                    </td>

                    {/* R:R */}
                    <td className="py-3 px-3.5 whitespace-nowrap text-slate-300 font-bold">
                      1:{item.immutable.risk_reward.toFixed(1)}
                    </td>

                    {/* Grade */}
                    <td className="py-3 px-3.5 whitespace-nowrap">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold border ${gradeBadge.bg} ${gradeBadge.border} ${gradeBadge.text}`}
                      >
                        {item.immutable.grade}
                      </span>
                    </td>

                    {/* Thesis */}
                    <td className="py-3 px-3.5 whitespace-nowrap">
                      <div
                        className="flex items-center gap-1.5 text-[11px] text-slate-400 font-mono max-w-[130px] truncate"
                        title={item.immutable.trade_thesis_id}
                      >
                        <Layers className="w-3 h-3 text-amber-400 shrink-0" />
                        <span className="truncate">{item.immutable.trade_thesis_id}</span>
                      </div>
                    </td>

                    {/* Action */}
                    <td className="py-3 px-3.5 whitespace-nowrap text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectSignal(item);
                        }}
                        className="px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-cyan-500/20 text-slate-300 hover:text-cyan-300 border border-slate-700 hover:border-cyan-500/40 transition-all flex items-center gap-1 ml-auto text-[11px]"
                      >
                        <span>HUD</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls Footer */}
      <div className="p-3.5 border-t border-slate-800/80 bg-slate-950/70 flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
        <div className="text-slate-400 text-[11px] flex items-center gap-2">
          <span>
            Showing <strong className="text-white">{filteredSignals.length > 0 ? (page - 1) * pageSize + 1 : 0}</strong> to{" "}
            <strong className="text-white">{Math.min(page * pageSize, filteredSignals.length)}</strong> of{" "}
            <strong className="text-white">{filteredSignals.length}</strong> signals
          </span>
          <span className="text-slate-600">|</span>
          <div className="flex items-center gap-1.5 text-slate-400">
            <span>Per page:</span>
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="bg-slate-900 border border-slate-800 rounded px-1.5 py-0.5 text-[11px] text-slate-300 focus:outline-none focus:border-cyan-500 font-mono"
            >
              <option value={15}>15</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 disabled:opacity-40 disabled:hover:border-slate-800 text-slate-300 text-[11px] flex items-center gap-1 transition-all"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span>Prev</span>
          </button>

          <span className="px-2.5 py-1 rounded-lg bg-slate-900/60 border border-slate-800 text-[11px] text-cyan-300 font-bold">
            Page {page} of {totalPages}
          </span>

          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 disabled:opacity-40 disabled:hover:border-slate-800 text-slate-300 text-[11px] flex items-center gap-1 transition-all"
          >
            <span>Next</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
