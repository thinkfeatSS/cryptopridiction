"use client";

import React, { useState } from "react";
import { usePortfolioQuery } from "@/hooks/useCryptoData";
import { useQueryClient } from "@tanstack/react-query";
import { resetPortfolio } from "@/lib/api";
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
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import TradeProgressBar from "./TradeProgressBar";

export default function PortfolioView() {
  const queryClient = useQueryClient();
  const { data: portfolio, isLoading } = usePortfolioQuery();
  const openPositions = portfolio?.open_positions || [];

  const [isResetting, setIsResetting] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [resetMessage, setResetMessage] = useState<string | null>(null);

  const handleReset = async () => {
    try {
      setIsResetting(true);
      const res = await resetPortfolio();
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["kpi"] });
      queryClient.invalidateQueries({ queryKey: ["forecast"] });
      setShowConfirmModal(false);
      setResetMessage(res.message || "Paper trading successfully reset to $100.00!");
      setTimeout(() => setResetMessage(null), 5000);
    } catch (err: any) {
      alert("Failed to reset paper trading: " + (err.message || err));
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800 relative">
      {/* Confirmation Modal */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-dark-950/80 backdrop-blur-sm p-4">
          <div className="max-w-md w-full rounded-2xl bg-dark-900 border border-slate-700 p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3 text-rose-400 mb-3">
              <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30">
                <AlertTriangle className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-black text-white">Reset Paper Trading?</h3>
                <p className="text-xs text-slate-400">This action will wipe all history</p>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Are you sure you want to reset paper trading? This will:
            </p>
            <ul className="text-xs text-slate-400 list-disc list-inside mt-2 space-y-1 font-mono">
              <li>Close &amp; delete all active open positions</li>
              <li>Wipe previous closed trade history</li>
              <li>Reset wallet capital back to clean <span className="text-emerald-400 font-bold">$100.00</span></li>
              <li>Activate Multi-Horizon Long &amp; Short trades ($10 max 10 trades)</li>
              <li>Enforce positive net profit target beating 100% real Binance fees (0.10% buy + 0.10% sell)</li>
            </ul>

            <div className="mt-5 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowConfirmModal(false)}
                disabled={isResetting}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-300 bg-dark-950 border border-slate-700 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={isResetting}
                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-500 transition-colors flex items-center gap-1.5 disabled:opacity-50 shadow-lg shadow-rose-900/30"
              >
                {isResetting ? (
                  <>
                    <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                    Resetting...
                  </>
                ) : (
                  <>
                    <RotateCcw className="h-3.5 w-3.5" />
                    Confirm Reset to $100.00
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Success Notification Banner */}
      {resetMessage && (
        <div className="mb-4 rounded-xl bg-emerald-950/80 border border-emerald-500/40 p-3.5 flex items-center justify-between gap-3 text-xs text-emerald-300 animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
            <span className="font-medium">{resetMessage}</span>
          </div>
          <button
            onClick={() => setResetMessage(null)}
            className="text-slate-400 hover:text-white text-xs font-mono"
          >
            ✕
          </button>
        </div>
      )}

      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-800/80 pb-4 gap-3">
        <div>
          <h2 className="text-lg font-black tracking-tight text-white flex items-center gap-2">
            💼 Active Open Paper Positions
            <span className="rounded-md bg-emerald-950 px-2 py-0.5 text-xs font-semibold text-emerald-400 border border-emerald-800">
              {openPositions.length} / 10 Active Trades
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Monitored 24/7 with 4-second price ticks &amp; automated take-profit executions
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-mono">
            <span className="rounded-md bg-purple-950/60 px-2 py-1 text-purple-300 border border-purple-800/60">
              💰 $100.00 Wallet ($10 / trade)
            </span>
            <span className="rounded-md bg-indigo-950/60 px-2 py-1 text-indigo-300 border border-indigo-800/60">
              📅 Multi-Horizon (Scalp, Swing, 4H, Daily)
            </span>
            <span className="rounded-md bg-cyan-950/60 px-2 py-1 text-cyan-300 border border-cyan-800/60">
              🎯 Net Profitable (Beats Fees)
            </span>
            <span className="rounded-md bg-amber-950/60 px-2 py-1 text-amber-300 border border-amber-800/60">
              ⚡ Binance Spot &amp; Futures (0.10% Fee)
            </span>
          </div>

          <button
            type="button"
            onClick={() => setShowConfirmModal(true)}
            className="rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 px-3 py-1.5 text-xs font-semibold flex items-center gap-1.5 transition-all hover:border-rose-500/60 ml-auto"
            title="Wipe previous open positions and reset paper trading wallet to $100.00"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset Paper Trading ($100)
          </button>
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
            The trading engine automatically opens virtual Long &amp; Short positions when institutional setups fire across Scalp, Swing, 4H, and Daily horizons beating real Binance fees.
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

                  {/* Institutional Bi-Directional SL <-> Buy/Entry <-> TP Live Progress Line */}
                  <TradeProgressBar
                    entryPrice={pos.entry_price}
                    currentPrice={pos.current_price}
                    tpPrice={pos.tp_price}
                    slPrice={pos.sl_price}
                    direction={pos.direction}
                    targetProgressPct={pos.target_progress_pct}
                  />
                </div>

                {/* Bottom PnL & Binance 100% Real Fee Bar */}
                <div className="mt-4 border-t border-slate-800/60 pt-2.5">
                  <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[10px] uppercase font-bold text-slate-400">Binance Fees:</span>
                      <span className="bg-dark-950 px-1.5 py-0.5 rounded border border-slate-800 text-slate-300">
                        Buy: -${(pos.buy_fee_usd ?? 0.01).toFixed(2)}
                      </span>
                      <span className="bg-dark-950 px-1.5 py-0.5 rounded border border-slate-800 text-slate-300">
                        Est Sell: -${(pos.est_sell_fee_usd ?? 0.01).toFixed(2)}
                      </span>
                    </div>

                    <div className="text-right">
                      <span className="text-[10px] text-slate-400 uppercase font-semibold">Net Unrealized PnL</span>
                    </div>
                  </div>

                  <div className="mt-1 flex items-baseline justify-between">
                    <div className="text-[10px] text-slate-400 font-mono">
                      Gross: <span className={pos.unrealized_gross_pnl_usd && pos.unrealized_gross_pnl_usd >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                        {pos.unrealized_gross_pnl_usd && pos.unrealized_gross_pnl_usd >= 0 ? "+" : ""}{formatUsd(pos.unrealized_gross_pnl_usd ?? 0.0)}
                      </span>
                    </div>

                    <div
                      className={`text-sm font-black font-mono ${
                        uPnl >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {uPnl >= 0 ? "+" : ""}{formatUsd(uPnl)} ({formatPercent(uPct)})
                    </div>
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
