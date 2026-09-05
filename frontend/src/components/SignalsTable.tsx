"use client";

import React, { useState } from "react";
import { useSignalsQuery, useDailySummaryQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd } from "@/lib/utils";
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
  Calendar,
} from "lucide-react";

interface SignalsTableProps {
  initialDate?: string;
}

export default function SignalsTable({ initialDate = "" }: SignalsTableProps) {
  const [search, setSearch] = useState("");
  const [dateFilter, setDateFilter] = useState(initialDate);
  const [outcomeFilter, setOutcomeFilter] = useState("");
  const [gradeFilter, setGradeFilter] = useState("");
  const [horizonFilter, setHorizonFilter] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 20;

  const { data: dailyData } = useDailySummaryQuery();
  const { data, isLoading, isFetching, refetch } = useSignalsQuery({
    search: search || undefined,
    date: dateFilter || undefined,
    outcome: outcomeFilter || undefined,
    grade: gradeFilter || undefined,
    horizon: horizonFilter || undefined,
    limit: pageSize,
    offset: page * pageSize,
  });

  const signals = data?.signals || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / pageSize);

  const handleDownloadCsv = () => {
    window.open("http://localhost:8000/api/signals/download-csv", "_blank");
  };

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      {/* Header & Controls Toolbar */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between border-b border-slate-800/80 pb-5">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            📋 Trader Signals Audit Ledger
            <span className="rounded-md bg-dark-900 px-2 py-0.5 text-xs font-semibold text-slate-400 border border-slate-800">
              {total} Total Signals
            </span>
            {dateFilter && (
              <span className="rounded-md bg-cyan-950 px-2 py-0.5 text-xs font-semibold text-cyan-300 border border-cyan-800">
                Filtered: {dateFilter}
              </span>
            )}
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Full verifiable win/loss history with live price evaluation & target audits
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="flex items-center gap-1.5 rounded-xl bg-dark-900 px-3 py-2 text-xs font-semibold text-slate-300 border border-slate-800 hover:bg-slate-800 hover:text-white transition-all"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin text-cyan-400" : ""}`} />
            Refresh
          </button>
          <button
            onClick={handleDownloadCsv}
            className="flex items-center gap-1.5 rounded-xl bg-cyan-600/20 px-3.5 py-2 text-xs font-semibold text-cyan-300 border border-cyan-500/40 hover:bg-cyan-600/30 hover:text-white transition-all shadow-sm"
          >
            <Download className="h-3.5 w-3.5" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Filter Ribbon */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-5">
        {/* Search Input */}
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search pair or ID..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="w-full rounded-xl bg-dark-900/90 pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 border border-slate-800 focus:border-cyan-500 focus:outline-none transition-all"
          />
        </div>

        {/* Date Filter Dropdown */}
        <select
          value={dateFilter}
          onChange={(e) => {
            setDateFilter(e.target.value);
            setPage(0);
          }}
          className="rounded-xl bg-dark-900/90 px-3 py-2 text-xs text-slate-300 border border-slate-800 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">📅 All Dates (Full History)</option>
          {dailyData?.map((d) => (
            <option key={d.date} value={d.date}>
              {d.date} ({d.won_count}W/{d.lost_count}L - {d.win_rate_pct}%)
            </option>
          ))}
        </select>

        {/* Outcome Filter */}
        <select
          value={outcomeFilter}
          onChange={(e) => {
            setOutcomeFilter(e.target.value);
            setPage(0);
          }}
          className="rounded-xl bg-dark-900/90 px-3 py-2 text-xs text-slate-300 border border-slate-800 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">🎯 All Outcomes</option>
          <option value="WON">🟢 Won (Take-Profit Hit)</option>
          <option value="LOST">🔴 Lost (Stop-Loss Hit)</option>
          <option value="PENDING">⏳ Pending Evaluation</option>
          <option value="EXPIRED">⏱️ Expired Trades</option>
        </select>

        {/* Grade Filter */}
        <select
          value={gradeFilter}
          onChange={(e) => {
            setGradeFilter(e.target.value);
            setPage(0);
          }}
          className="rounded-xl bg-dark-900/90 px-3 py-2 text-xs text-slate-300 border border-slate-800 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">💎 All Quality Grades</option>
          <option value="A+">💎 Grade A+ (Elite)</option>
          <option value="A">🟢 Grade A (High Conv)</option>
          <option value="B+">🟡 Grade B+ (Momentum)</option>
        </select>

        {/* Horizon Filter */}
        <select
          value={horizonFilter}
          onChange={(e) => {
            setHorizonFilter(e.target.value);
            setPage(0);
          }}
          className="rounded-xl bg-dark-900/90 px-3 py-2 text-xs text-slate-300 border border-slate-800 focus:border-cyan-500 focus:outline-none"
        >
          <option value="">⏱️ All Horizons</option>
          <option value="SCALP">⚡ Scalp (15M)</option>
          <option value="SWING">🌊 Swing (1H-2H)</option>
          <option value="MACRO">🚀 Macro (24H)</option>
        </select>
      </div>

      {/* Interactive Data Table */}
      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800/80">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
            <tr>
              <th className="py-3 px-4">Date / Rank</th>
              <th className="py-3 px-4">Asset & Horizon</th>
              <th className="py-3 px-4">Quality Grade</th>
              <th className="py-3 px-4">Side & Conviction</th>
              <th className="py-3 px-4">Entry Price</th>
              <th className="py-3 px-4">TP Targets</th>
              <th className="py-3 px-4">Stop-Loss</th>
              <th className="py-3 px-4">Outcome Status</th>
              <th className="py-3 px-4 text-right">Realized Return</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 bg-dark-950/40 font-mono">
            {isLoading ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-slate-500 font-sans">
                  Loading signals ledger from MySQL database...
                </td>
              </tr>
            ) : signals.length === 0 ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-slate-500 font-sans">
                  No signals matched the selected criteria.
                </td>
              </tr>
            ) : (
              signals.map((sig) => {
                const isLong = sig.direction === "LONG" || sig.direction === "BULLISH";
                const isWon = sig.outcome_label?.includes("WON");
                const isLost = sig.outcome_label?.includes("LOST");
                const isGradeAPlus = sig.quality_grade?.includes("A+");

                return (
                  <tr
                    key={sig.signal_id || sig.id}
                    className="hover:bg-slate-800/40 transition-colors"
                  >
                    {/* Date / Rank */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-bold text-white font-sans text-xs flex items-center gap-1">
                          {sig.rank || "#1"}
                        </span>
                        <span className="text-[10px] text-slate-400">{sig.date_utc} {sig.time_utc}</span>
                      </div>
                    </td>

                    {/* Asset & Horizon */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-bold text-white text-sm flex items-center gap-1">
                          {sig.symbol}
                        </span>
                        <span className="text-[10px] text-cyan-400 font-sans">{sig.horizon}</span>
                      </div>
                    </td>

                    {/* Quality Grade */}
                    <td className="py-3 px-4 font-sans">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-bold ${
                          isGradeAPlus
                            ? "bg-cyan-950 text-cyan-300 border border-cyan-600/40"
                            : "bg-emerald-950 text-emerald-300 border border-emerald-600/30"
                        }`}
                      >
                        {isGradeAPlus ? "💎 A+ Elite" : "🟢 Grade A"}
                      </span>
                    </td>

                    {/* Side & Conviction */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span
                          className={`inline-flex items-center gap-0.5 text-xs font-bold font-sans ${
                            isLong ? "text-emerald-400" : "text-rose-400"
                          }`}
                        >
                          {isLong ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                          {isLong ? "LONG" : "SHORT"}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          {sig.conviction_pct?.toFixed(1)}% Conv
                        </span>
                      </div>
                    </td>

                    {/* Entry Price */}
                    <td className="py-3 px-4 font-semibold text-white">
                      {formatUsd(sig.entry_price)}
                    </td>

                    {/* TP Targets */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col text-[11px]">
                        <span className="text-emerald-400">TP1: {formatUsd(sig.tp1_price)}</span>
                        <span className="text-slate-400">TP2: {formatUsd(sig.tp2_price)}</span>
                      </div>
                    </td>

                    {/* Stop-Loss */}
                    <td className="py-3 px-4 font-semibold text-rose-400">
                      {formatUsd(sig.sl_price)}
                    </td>

                    {/* Status & Outcome Badge */}
                    <td className="py-3 px-4 font-sans">
                      {isWon ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-950/80 px-2.5 py-1 text-[11px] font-bold text-emerald-300 border border-emerald-500/40">
                          <CheckCircle2 className="h-3 w-3" /> {sig.outcome_label}
                        </span>
                      ) : isLost ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-rose-950/80 px-2.5 py-1 text-[11px] font-bold text-rose-300 border border-rose-500/40">
                          <XCircle className="h-3 w-3" /> {sig.outcome_label}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-950/80 px-2.5 py-1 text-[11px] font-bold text-amber-300 border border-amber-500/40">
                          <Clock className="h-3 w-3" /> Pending ⏳
                        </span>
                      )}
                    </td>

                    {/* Realized Return */}
                    <td className="py-3 px-4 text-right">
                      {sig.realized_return_pct ? (
                        <span
                          className={`text-xs font-bold ${
                            sig.realized_return_pct.includes("+")
                              ? "text-emerald-400"
                              : "text-rose-400"
                          }`}
                        >
                          {sig.realized_return_pct}
                        </span>
                      ) : (
                        <span className="text-[11px] text-slate-500">Evaluating...</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="mt-4 flex items-center justify-between text-xs text-slate-400 border-t border-slate-800/80 pt-3">
        <span>
          Showing {signals.length > 0 ? page * pageSize + 1 : 0} to{" "}
          {Math.min((page + 1) * pageSize, total)} of {total} signals
        </span>

        <div className="flex items-center gap-2">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="flex items-center gap-1 rounded-lg bg-dark-900 px-3 py-1.5 text-xs font-semibold text-slate-300 border border-slate-800 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-800"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Previous
          </button>
          <span className="font-mono text-slate-300 font-bold">
            Page {page + 1} of {Math.max(1, totalPages)}
          </span>
          <button
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="flex items-center gap-1 rounded-lg bg-dark-900 px-3 py-1.5 text-xs font-semibold text-slate-300 border border-slate-800 disabled:opacity-40 disabled:pointer-events-none hover:bg-slate-800"
          >
            Next <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
