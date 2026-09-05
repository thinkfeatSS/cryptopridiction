"use client";

import React from "react";
import { usePortfolioQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd } from "@/lib/utils";
import { CheckCircle2, XCircle, Clock, ArrowUpRight, ArrowDownRight } from "lucide-react";

export default function ClosedTrades() {
  const { data: portfolio, isLoading } = usePortfolioQuery();
  const closedTrades = portfolio?.closed_trades_history || [];

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            📜 Completed Paper Trades Journal
            <span className="rounded-md bg-dark-900 px-2 py-0.5 text-xs font-semibold text-slate-400 border border-slate-800">
              {closedTrades.length} Completed
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Audit log with exact closing triggers, duration, and Binance fee breakdowns
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-xs text-slate-500 font-mono">
          Loading closed trades from database...
        </div>
      ) : closedTrades.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-500 font-sans">
          No completed trades recorded yet.
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-800/80">
          <table className="w-full text-left text-xs text-slate-300 font-mono">
            <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-3 px-4"># / Asset</th>
                <th className="py-3 px-4">Horizon / Side</th>
                <th className="py-3 px-4">Entry ➔ Exit Price</th>
                <th className="py-3 px-4">Closing Trigger</th>
                <th className="py-3 px-4">Duration</th>
                <th className="py-3 px-4">Binance Fee</th>
                <th className="py-3 px-4 text-right">Net Realized Return</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
              {closedTrades.map((t, idx) => {
                const isWon = t.outcome === "WON";
                const isLost = t.outcome === "LOST";
                const isLong = t.direction === "BULLISH" || t.direction === "LONG";
                const netPnl = t.realized_pnl_usd ?? 0.0;
                const netPct = t.realized_pnl_pct ?? 0.0;

                return (
                  <tr key={t.trade_id || idx} className="hover:bg-slate-800/40 transition-colors">
                    {/* Asset */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-bold text-white text-sm">{t.symbol}</span>
                        <span className="text-[10px] text-slate-500 font-sans">T-{closedTrades.length - idx}</span>
                      </div>
                    </td>

                    {/* Horizon / Side */}
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
                        <span className="text-[10px] text-cyan-400">{t.horizon}</span>
                      </div>
                    </td>

                    {/* Entry ➔ Exit Price */}
                    <td className="py-3 px-4">
                      <span className="text-slate-300">{formatUsd(t.entry_price)}</span>{" "}
                      <span className="text-slate-500">➔</span>{" "}
                      <span className="font-bold text-white">{formatUsd(t.exit_price)}</span>
                    </td>

                    {/* Closing Trigger */}
                    <td className="py-3 px-4 font-sans">
                      {isWon ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400 font-semibold text-xs">
                          <CheckCircle2 className="h-3.5 w-3.5" /> {t.exit_reason || "TAKE_PROFIT_HIT"}
                        </span>
                      ) : isLost ? (
                        <span className="inline-flex items-center gap-1 text-rose-400 font-semibold text-xs">
                          <XCircle className="h-3.5 w-3.5" /> {t.exit_reason || "STOP_LOSS_HIT"}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-slate-400 font-semibold text-xs">
                          <Clock className="h-3.5 w-3.5" /> {t.exit_reason || "EXPIRED"}
                        </span>
                      )}
                    </td>

                    {/* Duration */}
                    <td className="py-3 px-4 text-slate-400">{t.duration_str || "N/A"}</td>

                    {/* Fee */}
                    <td className="py-3 px-4 text-slate-400">-${t.binance_fee_usd?.toFixed(2) || "0.00"}</td>

                    {/* Net Realized Return */}
                    <td className="py-3 px-4 text-right">
                      <span
                        className={`text-sm font-bold ${
                          netPnl >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {netPnl >= 0 ? "+" : ""}{formatUsd(netPnl)} ({formatPercent(netPct)})
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
