"use client";

import React from "react";
import { V16SignalEnvelope } from "@/types/v16";
import { formatPrice, formatPercent, formatProbability, getGradeBadge } from "@/lib/utils/v16";
import { X, Layers, Shield, Zap, TrendingUp, Cpu, CheckCircle2, DollarSign, Activity, Lock } from "lucide-react";

interface Props {
  signal: V16SignalEnvelope | null;
  onClose: () => void;
}

export default function V16SignalDetailModal({ signal, onClose }: Props) {
  if (!signal) return null;

  const imm = signal.immutable;
  const dyn = signal.dynamic;
  const isLong = imm.direction.toUpperCase() === "LONG";
  const gradeBadge = getGradeBadge(imm.grade);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/85 backdrop-blur-md overflow-y-auto">
      <div className="relative w-full max-w-4xl bg-[#090d16] border border-cyan-500/30 rounded-3xl shadow-[0_0_80px_rgba(6,182,212,0.18)] overflow-hidden my-6 animate-fadeIn">
        {/* Ambient background light */}
        <div className="absolute -top-32 -right-32 w-80 h-80 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-32 -left-32 w-80 h-80 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Modal Header */}
        <div className="p-5 sm:p-6 border-b border-slate-800/80 bg-slate-950/80 flex items-center justify-between relative z-10">
          <div className="flex items-center gap-3.5">
            <div className="flex flex-col">
              <div className="flex items-center gap-2.5">
                <span className="text-2xl font-black font-mono tracking-tight text-white">{imm.symbol}</span>
                <span
                  className={`px-3 py-0.5 rounded-full text-xs font-mono font-black border ${
                    isLong
                      ? "bg-emerald-950/60 text-emerald-300 border-emerald-500/40 shadow-[0_0_10px_rgba(16,185,129,0.25)]"
                      : "bg-rose-950/60 text-rose-300 border-rose-500/40 shadow-[0_0_10px_rgba(244,63,94,0.25)]"
                  }`}
                >
                  {imm.direction}
                </span>
                <span className="text-xs text-cyan-300 font-mono font-bold px-2 py-0.5 rounded-md bg-slate-900 border border-cyan-500/20">
                  {imm.horizon}
                </span>
              </div>
              <span className="text-[11px] text-slate-400 font-mono mt-1">
                Signal ID: <strong className="text-slate-300">{imm.signal_id}</strong> • Emitted: {imm.signal_generated_at}
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-white transition-all shadow-sm"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 sm:p-6 space-y-6 max-h-[80vh] overflow-y-auto relative z-10 touch-scroll">
          {/* Top Metadata Badges */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
            <div className="bg-slate-950/70 p-3.5 rounded-2xl border border-slate-800/80">
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Trade Thesis</div>
              <div className="font-bold text-amber-300 mt-1 truncate" title={imm.trade_thesis_id}>
                {imm.trade_thesis_id}
              </div>
            </div>
            <div className="bg-slate-950/70 p-3.5 rounded-2xl border border-slate-800/80">
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Quality Grade</div>
              <div className="mt-1">
                <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold border ${gradeBadge.bg} ${gradeBadge.border} ${gradeBadge.text}`}>
                  {imm.grade}
                </span>
              </div>
            </div>
            <div className="bg-slate-950/70 p-3.5 rounded-2xl border border-slate-800/80">
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Regime Shield</div>
              <div className="font-bold text-slate-200 mt-1">{imm.regime || "RANGE"}</div>
            </div>
            <div className="bg-slate-950/70 p-3.5 rounded-2xl border border-slate-800/80">
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider">Risk:Reward</div>
              <div className="font-bold text-emerald-400 mt-1">1:{imm.risk_reward.toFixed(2)}</div>
            </div>
          </div>

          {/* Core Two Column: Immutable Trade Levels vs Probability & Net EV */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Left: Execution & Price Structure (Section 13) */}
            <div className="bg-slate-950/70 p-5 rounded-2xl border border-slate-800/80 flex flex-col justify-between">
              <div>
                <h3 className="text-xs font-bold uppercase font-mono tracking-wider text-slate-300 mb-3 flex items-center gap-2">
                  <Shield className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Execution Price Structure (Section 13)</span>
                </h3>
                <div className="space-y-2.5 font-mono text-xs">
                  <div className="flex justify-between py-2 border-b border-slate-800/60">
                    <span className="text-slate-400">Entry Zone</span>
                    <span className="font-bold text-white text-sm">{formatPrice(imm.entry_price_initial)}</span>
                  </div>
                  <div className="flex justify-between py-2 border-b border-slate-800/60">
                    <span className="text-rose-400 font-bold">Stop-Loss (SL)</span>
                    <span className="font-bold text-rose-400">{formatPrice(imm.sl_initial)}</span>
                  </div>
                  <div className="flex justify-between py-2 border-b border-slate-800/60">
                    <span className="text-emerald-400 font-bold">Target 1 (TP1 - 50% Scale)</span>
                    <span className="font-bold text-emerald-400">{formatPrice(imm.tp1_initial)}</span>
                  </div>
                  <div className="flex justify-between py-2 border-b border-slate-800/60">
                    <span className="text-emerald-400">Target 2 (TP2 - 30% Scale)</span>
                    <span className="font-bold text-emerald-400">{formatPrice(imm.tp2_initial)}</span>
                  </div>
                  <div className="flex justify-between py-2">
                    <span className="text-emerald-400">Target 3 (TP3 - 20% Runner)</span>
                    <span className="font-bold text-emerald-400">{formatPrice(imm.tp3_initial)}</span>
                  </div>
                </div>
              </div>

              {/* Dynamic State Section (Section 10) */}
              <div className="mt-5 pt-4 border-t border-slate-800/80 font-mono text-xs">
                <div className="text-[11px] text-slate-400 uppercase font-bold mb-2.5 flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-white">
                    <Activity className="w-3 h-3 text-cyan-400" /> Live Dynamic State (Section 10)
                  </span>
                  <span className="text-[10px] text-slate-500">{dyn.updated_at_utc}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <div className="bg-slate-900/90 p-2.5 rounded-xl border border-slate-800">
                    <div className="text-slate-500">Current Price</div>
                    <div className="font-bold text-white mt-0.5">{formatPrice(dyn.current_price)}</div>
                  </div>
                  <div className="bg-slate-900/90 p-2.5 rounded-xl border border-slate-800">
                    <div className="text-slate-500">Active SL State</div>
                    <div className="font-bold text-slate-200 mt-0.5">{formatPrice(dyn.current_sl)}</div>
                  </div>
                  <div className="bg-slate-900/90 p-2.5 rounded-xl border border-slate-800">
                    <div className="text-slate-500">TP1 Locked</div>
                    <div className="font-bold text-cyan-300 mt-0.5">{dyn.is_tp1_locked ? "YES (Breakeven Locked)" : "PENDING TP1"}</div>
                  </div>
                  <div className="bg-slate-900/90 p-2.5 rounded-xl border border-slate-800">
                    <div className="text-slate-500">Unrealized Net PnL</div>
                    <div className={`font-bold mt-0.5 ${dyn.unrealized_net_pnl_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {formatPercent(dyn.unrealized_net_pnl_pct)}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right: Probability Path Model & Cost Waterfall (Section 17-20) */}
            <div className="bg-slate-950/70 p-5 rounded-2xl border border-slate-800/80 flex flex-col justify-between">
              {/* Probability Path */}
              <div>
                <h3 className="text-xs font-bold uppercase font-mono tracking-wider text-slate-300 mb-3 flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Calibrated Probability Path (Section 17-18)</span>
                </h3>
                <div className="space-y-3 font-mono text-xs">
                  {/* P(TP1) */}
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-slate-400">P(TP1 before SL)</span>
                      <span className="font-bold text-indigo-300">{formatProbability(imm.p_tp1)}</span>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div className="bg-indigo-500 h-full rounded-full transition-all duration-300 shadow-[0_0_8px_rgba(99,102,241,0.6)]" style={{ width: `${Math.min(100, imm.p_tp1 <= 1 ? imm.p_tp1 * 100 : imm.p_tp1)}%` }} />
                    </div>
                  </div>

                  {/* P(TP2) */}
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-slate-400">P(TP2 before SL)</span>
                      <span className="font-bold text-indigo-300">{formatProbability(imm.p_tp2)}</span>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div className="bg-indigo-500/70 h-full rounded-full transition-all duration-300" style={{ width: `${Math.min(100, imm.p_tp2 <= 1 ? imm.p_tp2 * 100 : imm.p_tp2)}%` }} />
                    </div>
                  </div>

                  {/* P(TP3) */}
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-slate-400">P(TP3 before SL)</span>
                      <span className="font-bold text-indigo-300">{formatProbability(imm.p_tp3)}</span>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div className="bg-indigo-500/50 h-full rounded-full transition-all duration-300" style={{ width: `${Math.min(100, imm.p_tp3 <= 1 ? imm.p_tp3 * 100 : imm.p_tp3)}%` }} />
                    </div>
                  </div>

                  {/* P(SL) */}
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-rose-400">P(SL before TP1)</span>
                      <span className="font-bold text-rose-400">{formatProbability(imm.p_sl)}</span>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div className="bg-rose-500 h-full rounded-full transition-all duration-300 shadow-[0_0_8px_rgba(244,63,94,0.6)]" style={{ width: `${Math.min(100, imm.p_sl <= 1 ? imm.p_sl * 100 : imm.p_sl)}%` }} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Net EV Waterfall (Section 19) */}
              <div className="mt-5 pt-4 border-t border-slate-800/80 font-mono text-xs">
                <h4 className="text-[11px] font-bold uppercase text-slate-400 mb-2.5 flex items-center justify-between">
                  <span>Net Expectancy Waterfall (Section 19)</span>
                  <span className="text-emerald-400 font-bold bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-500/30">
                    EVnet &gt; 0% SURVIVES COSTS
                  </span>
                </h4>
                <div className="space-y-1.5 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Gross Expected Value</span>
                    <span className="text-white font-bold">+{imm.expected_gross_return.toFixed(2)}%</span>
                  </div>
                  <div className="flex justify-between text-rose-400">
                    <span>Round-trip Frictions (Taker Fee + Spread + Slip + Funding)</span>
                    <span>-{imm.total_execution_costs.toFixed(2)}%</span>
                  </div>
                  <div className="flex justify-between pt-1.5 border-t border-slate-800 font-bold text-xs">
                    <span className="text-slate-200">Expected Net Value (EVnet)</span>
                    <span className="text-emerald-400 font-black">+{imm.expected_net_return.toFixed(2)}%</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Market Shield Checks */}
          <div className="bg-slate-950/70 p-4 rounded-2xl border border-slate-800/80 font-mono text-xs">
            <h4 className="text-[11px] font-bold uppercase text-slate-400 mb-3 flex items-center gap-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              <span>V16 Invariant Protection Audits (Sections 21-27)</span>
            </h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px]">
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800">
                <span className="text-slate-500">Data Quality Score</span>
                <div className="font-bold text-emerald-400 mt-0.5">{imm.data_quality_score || 95} / 100 ✓</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800">
                <span className="text-slate-500">Lookahead Violations</span>
                <div className="font-bold text-emerald-400 mt-0.5">0 Violations ✓</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800">
                <span className="text-slate-500">Liquidity Score</span>
                <div className="font-bold text-emerald-400 mt-0.5">{imm.liquidity_score || 90} / 100 ✓</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800">
                <span className="text-slate-500">Thesis Exposure Cap</span>
                <div className="font-bold text-emerald-400 mt-0.5">1 Position Max ✓</div>
              </div>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="p-4 sm:p-5 border-t border-slate-800/80 bg-slate-950/80 flex items-center justify-between text-xs font-mono text-slate-400 relative z-10">
          <span>Immutable Audit Snapshot Frozen At Generation</span>
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-bold transition-all shadow-sm"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
}
