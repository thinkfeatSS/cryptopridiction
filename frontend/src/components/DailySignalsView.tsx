"use client";

import React from "react";
import { useDailySummaryQuery } from "@/hooks/useCryptoData";
import { formatPercent } from "@/lib/utils";
import {
  Calendar,
  CheckCircle2,
  XCircle,
  Clock,
  TrendingUp,
  Award,
  Sparkles,
} from "lucide-react";

interface DailySignalsViewProps {
  selectedDate?: string;
  onSelectDate: (date: string) => void;
}

export default function DailySignalsView({
  selectedDate,
  onSelectDate,
}: DailySignalsViewProps) {
  const { data: dailySummaries, isLoading } = useDailySummaryQuery();

  const summaries = dailySummaries || [];

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            <Calendar className="h-5 w-5 text-cyan-400" />
            Daily Performance & Win/Loss Audit Breakdown
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Day-by-day signals tracking, resolved win rate %, and daily realized cumulative returns
          </p>
        </div>

        {selectedDate && (
          <button
            onClick={() => onSelectDate("")}
            className="rounded-lg bg-dark-900 px-3 py-1.5 text-xs font-semibold text-cyan-300 border border-cyan-700/50 hover:bg-cyan-950 transition-all"
          >
            Clear Date Filter (Show All Days)
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-xs text-slate-500 font-mono">
          Loading daily audit breakdown...
        </div>
      ) : summaries.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-500 font-sans">
          No daily records found.
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
          {summaries.map((day) => {
            const isSelected = selectedDate === day.date;
            const decisive = day.won_count + day.lost_count;

            return (
              <div
                key={day.date}
                onClick={() => onSelectDate(isSelected ? "" : day.date)}
                className={`cursor-pointer rounded-xl p-4 border transition-all duration-200 ${
                  isSelected
                    ? "bg-cyan-950/60 border-cyan-400 shadow-lg shadow-cyan-500/20"
                    : "bg-dark-900/80 border-slate-800 hover:border-slate-700 hover:bg-dark-850"
                }`}
              >
                {/* Date Header */}
                <div className="flex items-center justify-between border-b border-slate-800/60 pb-2">
                  <span className="font-bold text-white text-xs flex items-center gap-1.5">
                    <Calendar className="h-3.5 w-3.5 text-cyan-400" />
                    {day.date}
                  </span>
                  <span className="rounded bg-dark-950 px-2 py-0.5 text-[10px] font-mono text-slate-400">
                    {day.total_signals} Signals
                  </span>
                </div>

                {/* Win / Lost Metrics */}
                <div className="mt-3 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1 text-emerald-400 font-bold">
                      <CheckCircle2 className="h-3.5 w-3.5" /> {day.won_count}W
                    </span>
                    <span className="flex items-center gap-1 text-rose-400 font-bold">
                      <XCircle className="h-3.5 w-3.5" /> {day.lost_count}L
                    </span>
                    <span className="text-amber-400 font-medium text-[11px]">
                      ⏳ {day.pending_count}
                    </span>
                  </div>

                  <span className="font-black text-cyan-300">
                    {day.win_rate_pct.toFixed(1)}% WR
                  </span>
                </div>

                {/* Cumulative Return for Day */}
                <div className="mt-2.5 flex items-center justify-between border-t border-slate-800/60 pt-2 text-xs">
                  <span className="text-[11px] text-slate-400">Day Return:</span>
                  <span
                    className={`font-black font-mono ${
                      day.cumulative_return_pct >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {formatPercent(day.cumulative_return_pct)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
