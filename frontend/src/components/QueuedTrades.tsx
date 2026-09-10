"use client";

import React from "react";
import { usePortfolioQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd } from "@/lib/utils";
import {
  Clock,
  ArrowUpRight,
  Sparkles,
  ShieldCheck,
  TrendingUp,
  Layers,
  AlertCircle,
} from "lucide-react";

export default function QueuedTrades() {
  const { data: portfolio, isLoading } = usePortfolioQuery();
  const queuedTrades = portfolio?.queued_trades || [];
  const openPositionsCount = portfolio?.open_positions?.length || 0;

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-800/80 pb-4 gap-3">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            ⏳ Qualified Waitlist &amp; Queued Trades
            <span
              className={`rounded-md px-2 py-0.5 text-xs font-semibold border ${
                queuedTrades.length > 0
                  ? "bg-amber-950 text-amber-300 border-amber-800"
                  : "bg-dark-900 text-slate-400 border-slate-800"
              }`}
            >
              {queuedTrades.length} In Waitlist
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            100% Qualified Spot Long setups (&ge;+5.0% net profit under Convert spread &amp; Past Won &gt; Lost) held while active queue is at full capacity (10/10)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="rounded-md bg-cyan-950/60 px-2.5 py-1 text-xs font-mono text-cyan-300 border border-cyan-800/60 flex items-center gap-1.5">
            <Layers className="h-3.5 w-3.5" />
            Active Slots: {openPositionsCount} / 10
          </span>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-xs text-slate-500 font-mono">
          Checking queued qualified setups...
        </div>
      ) : queuedTrades.length === 0 ? (
        <div className="py-8 text-center text-slate-400">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-dark-900 border border-slate-800 text-slate-500 mb-2">
            <ShieldCheck className="h-5 w-5 text-emerald-400" />
          </div>
          <h3 className="text-xs font-bold text-white">No Queued Trades Waiting</h3>
          <p className="text-[11px] text-slate-500 mt-0.5 max-w-md mx-auto">
            All currently qualified trades have either been admitted directly into the 10 active slots, or the engine is waiting for 4H/24H/Daily setups that satisfy both the &ge;+5.0% net return hurdle (under Convert spread) and positive historical track record.
          </p>
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-xl border border-amber-900/40 bg-amber-950/10">
          <table className="w-full text-left text-xs text-slate-300 font-mono">
            <thead className="bg-dark-900/95 uppercase text-[10px] font-bold tracking-wider text-amber-400/90 border-b border-amber-900/40">
              <tr>
                <th className="py-3 px-4"># / Asset</th>
                <th className="py-3 px-4">Horizon / Strategy</th>
                <th className="py-3 px-4">Entry ➔ Target (TP1)</th>
                <th className="py-3 px-4">Historical Win/Loss</th>
                <th className="py-3 px-4">Est. Net Profit ($10 Size)</th>
                <th className="py-3 px-4">Status / Waitlist Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 bg-dark-950/60">
              {queuedTrades.map((t, idx) => {
                const estProfit = t.est_net_profit_usd ?? 0.0;
                const estPct = t.est_net_gain_pct ?? 0.0;

                return (
                  <tr
                    key={t.trade_id || idx}
                    className="hover:bg-amber-500/5 transition-colors"
                  >
                    {/* Asset */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-black text-white text-sm flex items-center gap-1.5">
                          {t.symbol}
                          <span className="text-[10px] font-semibold text-emerald-400 bg-emerald-950/70 border border-emerald-800/60 rounded px-1.5 py-0.2">
                            SPOT
                          </span>
                        </span>
                        <span className="text-[10px] text-slate-500 font-sans">
                          Queue #{idx + 1}
                        </span>
                      </div>
                    </td>

                    {/* Horizon / Strategy */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="inline-flex items-center gap-1 text-xs font-bold text-emerald-400 font-sans">
                          <ArrowUpRight className="h-3.5 w-3.5" />
                          SPOT LONG
                        </span>
                        <span className="text-[10px] text-cyan-400 font-mono">
                          {t.horizon}
                        </span>
                      </div>
                    </td>

                    {/* Entry ➔ Target Price */}
                    <td className="py-3 px-4">
                      <span className="text-slate-300">{formatUsd(t.entry_price)}</span>{" "}
                      <span className="text-slate-500">&rarr;</span>{" "}
                      <span className="font-bold text-emerald-400">
                        {formatUsd(t.tp1_price || t.tp_price)}
                      </span>
                    </td>

                    {/* Track Record */}
                    <td className="py-3 px-4 font-sans">
                      <span className="inline-flex items-center gap-1 text-emerald-300 font-semibold text-xs bg-emerald-950/60 border border-emerald-800/50 rounded-md px-2 py-0.5">
                        <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                        {t.past_won} Won / {t.past_lost} Lost
                      </span>
                    </td>

                    {/* Est Net Profit on $5 */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="text-sm font-black text-emerald-400 font-mono">
                          +{formatUsd(estProfit)}
                        </span>
                        <span className="text-[10px] text-emerald-300 font-sans">
                          +{estPct.toFixed(1)}% Net Target
                        </span>
                      </div>
                    </td>

                    {/* Status */}
                    <td className="py-3 px-4 font-sans">
                      <span className="inline-flex items-center gap-1 text-amber-300 font-medium text-xs bg-amber-950/60 border border-amber-800/50 rounded-md px-2.5 py-1">
                        <Clock className="h-3.5 w-3.5 text-amber-400 animate-pulse" />
                        Next In Line (Queue Full 3/3)
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
