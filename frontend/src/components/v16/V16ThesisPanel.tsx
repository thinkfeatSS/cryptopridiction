"use client";

import React from "react";
import { V16TradeThesis } from "@/types/v16";
import { formatPercent } from "@/lib/utils/v16";
import { Layers, ArrowRight, ShieldCheck, CheckCircle2, Radio, Lock } from "lucide-react";

interface Props {
  theses: V16TradeThesis[];
  isLoading: boolean;
}

export default function V16ThesisPanel({ theses, isLoading }: Props) {
  if (isLoading) {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-5 animate-pulse text-slate-500 font-mono text-xs flex items-center justify-center min-h-[220px]">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-amber-400 animate-spin" />
          <span>Clustering multi-horizon trade theses across 110 assets...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-5 shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col justify-between">
      {/* Background soft ambient radial */}
      <div className="absolute -top-12 -left-12 w-48 h-48 bg-amber-500/10 rounded-full blur-2xl pointer-events-none" />

      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3 relative z-10">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-amber-950/60 border border-amber-500/30 text-amber-400">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-bold tracking-wider text-white font-mono uppercase">
              Trade Thesis Clusters
            </h2>
            <span className="text-[10px] text-slate-400 font-mono">Cross-Timeframe Root Ideas & Correlation Deduplication</span>
          </div>
        </div>
        <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-slate-950/80 border border-slate-700 text-slate-300">
          Section 25 Enforced
        </span>
      </div>

      <div className="my-3 text-xs text-slate-400 relative z-10">
        Simultaneous predictions across 15M, 1H, and 1D are unified into single root theses to eliminate redundant exposure and prevent stack liquidation risk.
      </div>

      {/* Theses List */}
      <div className="space-y-2.5 font-mono text-xs max-h-[220px] overflow-y-auto pr-1 relative z-10">
        {theses.length === 0 ? (
          <div className="py-8 px-4 rounded-xl border border-dashed border-slate-800 bg-slate-950/30 text-center text-slate-400 text-xs flex flex-col items-center justify-center gap-2">
            <Radio className="w-6 h-6 text-slate-600 animate-pulse" />
            <span className="font-bold text-slate-300">No Multi-Horizon Theses Clustered Currently</span>
            <span className="text-[11px] text-slate-500 max-w-sm">
              Section 25 Zero Stacking Guard will cluster overlapping 15M/1H/1D signals the instant correlated triggers fire.
            </span>
          </div>
        ) : (
          theses.slice(0, 10).map((th) => {
            const isLong = th.direction.toUpperCase() === "LONG";
            const isActive = th.is_active || (th.active_signals_count && th.active_signals_count > 0);

            return (
              <div
                key={th.thesis_id}
                className={`p-3 rounded-xl bg-slate-950/70 border transition-all duration-200 ${
                  isActive
                    ? "border-amber-500/50 shadow-[0_0_15px_rgba(251,191,36,0.1)]"
                    : "border-slate-800/80 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white text-sm">{th.symbol}</span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-black border ${
                        isLong
                          ? "bg-emerald-950/60 text-emerald-300 border-emerald-500/30"
                          : "bg-rose-950/60 text-rose-300 border-rose-500/30"
                      }`}
                    >
                      {th.direction}
                    </span>
                    {isActive ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 flex items-center gap-1 shadow-sm">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
                        </span>
                        ACTIVE
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-900 text-slate-400 border border-slate-800">
                        RESOLVED
                      </span>
                    )}
                  </div>
                  <span className="text-emerald-400 font-black text-xs">
                    Peak EV: {formatPercent(th.highest_net_ev)}
                  </span>
                </div>

                <div className="mt-1.5 text-[11px] text-slate-500 truncate" title={th.thesis_id}>
                  Thesis: <span className="text-slate-400 font-mono">{th.thesis_id}</span>
                  <span className="ml-2 text-slate-500 font-normal">({th.signals.length} {th.signals.length === 1 ? 'Signal' : 'Signals'} Clustered)</span>
                </div>

                {/* Horizons Confirmed */}
                <div className="mt-2 flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-800/50">
                  <span className="text-[10px] text-slate-500">Horizons:</span>
                  {th.participating_horizons.map((hz) => (
                    <span
                      key={hz}
                      className="px-2 py-0.5 rounded-md bg-slate-900 text-cyan-300 text-[10px] border border-cyan-500/20 font-bold"
                    >
                      {hz}
                    </span>
                  ))}
                  <span className="ml-auto text-[10px] text-amber-300 font-bold flex items-center gap-1">
                    <Lock className="w-2.5 h-2.5 text-amber-400" /> Max 1 Pos Cap Active
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="mt-3 pt-3 border-t border-slate-800/80 text-[10px] text-slate-500 font-mono flex items-center justify-between relative z-10">
        <span>Portfolio Risk Engine: Section 27 Cap</span>
        <span className="text-emerald-400 flex items-center gap-1.5 font-bold">
          <ShieldCheck className="w-3.5 h-3.5" /> Zero Stacking Guard Active
        </span>
      </div>
    </div>
  );
}
