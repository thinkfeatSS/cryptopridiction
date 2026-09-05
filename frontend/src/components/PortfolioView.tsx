"use client";

import React from "react";
import { usePortfolioQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd } from "@/lib/utils";
import {
  TrendingUp,
  Clock,
  Target,
  ArrowUpRight,
  ArrowDownRight,
  DollarSign,
  ShieldCheck,
  Zap,
} from "lucide-react";

export default function PortfolioView() {
  const { data: portfolio, isLoading } = usePortfolioQuery();
  const openPositions = portfolio?.open_positions || [];

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            💼 Active Open Paper Positions
            <span className="rounded-md bg-emerald-950 px-2 py-0.5 text-xs font-semibold text-emerald-400 border border-emerald-800">
              {openPositions.length} Live Trades
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Monitored 24/7 with 10-second price ticks & automated take-profit executions
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-xs text-slate-500 font-mono">
          Syncing open paper positions from database...
        </div>
      ) : openPositions.length === 0 ? (
        <div className="py-12 text-center text-slate-400">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-dark-900 border border-slate-800 text-slate-500 mb-3">
            <Zap className="h-6 w-6" />
          </div>
          <h3 className="text-sm font-bold text-white">No Open Positions Active</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            The trading engine will automatically open virtual positions when Grade A+ setups fire on the 15-minute candle close.
          </p>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {openPositions.map((pos) => {
            const isLong = pos.direction === "BULLISH" || pos.direction === "LONG";
            const uPnl = pos.unrealized_pnl_usd ?? 0.0;
            const uPct = pos.unrealized_pnl_pct ?? 0.0;
            const progress = Math.max(-100, Math.min(100, pos.target_progress_pct ?? 0.0));

            return (
              <div
                key={pos.trade_id || pos.id}
                className="rounded-xl bg-dark-900/90 p-4 border border-slate-800/80 hover:border-slate-700 transition-all flex flex-col justify-between"
              >
                <div>
                  {/* Top Bar: Symbol, Horizon, Direction */}
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-base font-black text-white">{pos.symbol}</h4>
                      <span className="text-[11px] text-cyan-400 font-mono">{pos.horizon}</span>
                    </div>

                    <span
                      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-bold ${
                        isLong
                          ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                          : "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                      }`}
                    >
                      {isLong ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
                      {isLong ? "LONG" : "SHORT"}
                    </span>
                  </div>

                  {/* Price Comparison */}
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono rounded-lg bg-dark-950/80 p-2.5 border border-slate-800/60">
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-400">Entry</span>
                      <p className="text-white font-bold">{formatUsd(pos.entry_price)}</p>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-cyan-400">Current</span>
                      <p className="text-cyan-300 font-bold">{formatUsd(pos.current_price)}</p>
                    </div>
                    <div className="border-t border-slate-800/60 pt-1.5">
                      <span className="text-[10px] uppercase font-bold text-emerald-400">TP Target</span>
                      <p className="text-emerald-400">{formatUsd(pos.tp_price)}</p>
                    </div>
                    <div className="border-t border-slate-800/60 pt-1.5">
                      <span className="text-[10px] uppercase font-bold text-rose-400">Stop-Loss</span>
                      <p className="text-rose-400">{formatUsd(pos.sl_price)}</p>
                    </div>
                  </div>

                  {/* Progress to Target Bar */}
                  <div className="mt-3">
                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="text-slate-400 flex items-center gap-1">
                        <Target className="h-3 w-3 text-cyan-400" /> Progress to TP
                      </span>
                      <span className={`font-bold ${progress >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {progress >= 0 ? "+" : ""}{progress.toFixed(1)}%
                      </span>
                    </div>
                    <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                      <div
                        className={`h-full transition-all duration-500 rounded-full ${
                          progress >= 0 ? "bg-gradient-to-r from-cyan-500 to-emerald-400" : "bg-rose-500"
                        }`}
                        style={{ width: `${Math.max(5, Math.abs(progress))}%` }}
                      />
                    </div>
                  </div>
                </div>

                {/* Bottom PnL & Fee Bar */}
                <div className="mt-4 flex items-center justify-between border-t border-slate-800/60 pt-2.5 text-xs">
                  <div>
                    <span className="text-[10px] text-slate-400">Fee (Est):</span>{" "}
                    <span className="text-slate-300 font-mono">-${pos.unrealized_fee_usd?.toFixed(2) || "0.00"}</span>
                  </div>
                  <div className="text-right">
                    <span
                      className={`text-sm font-black font-mono ${
                        uPnl >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {uPnl >= 0 ? "+" : ""}{formatUsd(uPnl)} ({formatPercent(uPct)})
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
