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
  const rawPositions = portfolio?.open_positions || [];
  const openPositions = React.useMemo(() => {
    return rawPositions.filter((pos: any) => {
      const sym = (pos.symbol || "").toUpperCase().replace("/USDT", "").replace("USDT", "").trim();
      if (!sym) return false;
      if (sym.includes("OLD") || sym.includes("DELISTED") || sym === "USDSOLD") return false;
      if (sym.endsWith("B") && sym !== "BNB" && sym !== "ARB") return false;
      return true;
    });
  }, [rawPositions]);

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
      setResetMessage(res.message || "Paper trading successfully reset to $1,000.00!");
      setTimeout(() => setResetMessage(null), 5000);
    } catch (err: any) {
      alert("Failed to reset paper trading: " + (err.message || err));
    } finally {
      setIsResetting(false);
    }
  };

  const rawDesks = (portfolio as any)?.desks || {};
  const scalpDesk = rawDesks.scalp || { name: "⚡ Scalp Desk", allocated_usd: 350.0, open_positions: 0, active_slots: 0, max_slots: 2, win_rate_pct: 0.0, realized_pnl_usd: 0.0, unrealized_pnl_usd: 0.0, total_pnl_usd: 0.0 };
  const dayDesk = rawDesks.day || rawDesks.intraday || { name: "⏳ Day Trading Desk", allocated_usd: 400.0, open_positions: 0, active_slots: 0, max_slots: 2, win_rate_pct: 0.0, realized_pnl_usd: 0.0, unrealized_pnl_usd: 0.0, total_pnl_usd: 0.0 };
  const swingDesk = rawDesks.swing || rawDesks.macro || { name: "🌊 Swing Desk", allocated_usd: 250.0, open_positions: 0, active_slots: 0, max_slots: 1, win_rate_pct: 0.0, realized_pnl_usd: 0.0, unrealized_pnl_usd: 0.0, total_pnl_usd: 0.0 };

  const sharpe = (portfolio as any)?.sharpe_ratio ?? 0.0;
  const sortino = (portfolio as any)?.sortino_ratio ?? 0.0;
  const expectancy = (portfolio as any)?.expectancy_usd ?? 0.0;
  const profitFactor = (portfolio as any)?.profit_factor ?? 0.0;

  const scalpSlots = scalpDesk.open_positions ?? scalpDesk.active_slots ?? 0;
  const daySlots = dayDesk.open_positions ?? dayDesk.active_slots ?? 0;
  const swingSlots = swingDesk.open_positions ?? swingDesk.active_slots ?? 0;

  const scalpPnl = scalpDesk.total_pnl_usd !== undefined ? scalpDesk.total_pnl_usd : (scalpDesk.realized_pnl_usd ?? 0.0);
  const dayPnl = dayDesk.total_pnl_usd !== undefined ? dayDesk.total_pnl_usd : (dayDesk.realized_pnl_usd ?? 0.0);
  const swingPnl = swingDesk.total_pnl_usd !== undefined ? swingDesk.total_pnl_usd : (swingDesk.realized_pnl_usd ?? 0.0);

  return (
    <div className="space-y-6">
      {/* 3-Desk Partitioning Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
        {/* Scalp Desk */}
        <div className="glass-panel rounded-2xl p-4 border border-cyan-500/20 bg-cyan-950/20 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-black uppercase tracking-wider text-cyan-300 flex items-center gap-1.5">
              ⚡ Scalp Desk (35%)
            </span>
            <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${scalpSlots > 0 ? "bg-cyan-500/30 text-cyan-200 border-cyan-400/50 font-bold" : "bg-cyan-500/20 text-cyan-300 border-cyan-500/30"}`}>
              {scalpSlots} / {scalpDesk.max_slots ?? 2} Slots
            </span>
          </div>
          <div className="mt-2.5 flex items-baseline justify-between">
            <div>
              <p className="text-xl font-black text-white font-mono">${(scalpDesk.allocated_usd ?? 350.0).toFixed(0)}</p>
              <p className="text-[10px] text-slate-400">15M Scalp Timeframe (5x Leverage)</p>
            </div>
            <div className="text-right">
              <span className={`text-xs font-bold font-mono ${scalpPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {scalpPnl >= 0 ? "+" : ""}${scalpPnl.toFixed(2)}
              </span>
              <p className="text-[10px] text-slate-400">Tier-0 BE: +0.80%</p>
            </div>
          </div>
        </div>

        {/* Day Trading Desk */}
        <div className="glass-panel rounded-2xl p-4 border border-indigo-500/20 bg-indigo-950/20 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-black uppercase tracking-wider text-indigo-300 flex items-center gap-1.5">
              ⏳ Day Trading Desk (40%)
            </span>
            <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${daySlots > 0 ? "bg-indigo-500/30 text-indigo-200 border-indigo-400/50 font-bold" : "bg-indigo-500/20 text-indigo-300 border-indigo-500/30"}`}>
              {daySlots} / {dayDesk.max_slots ?? 2} Slots
            </span>
          </div>
          <div className="mt-2.5 flex items-baseline justify-between">
            <div>
              <p className="text-xl font-black text-white font-mono">${(dayDesk.allocated_usd ?? 400.0).toFixed(0)}</p>
              <p className="text-[10px] text-slate-400">1H Day Trade Timeframe (3x Leverage)</p>
            </div>
            <div className="text-right">
              <span className={`text-xs font-bold font-mono ${dayPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {dayPnl >= 0 ? "+" : ""}${dayPnl.toFixed(2)}
              </span>
              <p className="text-[10px] text-slate-400">Tier-0 BE: +1.25%</p>
            </div>
          </div>
        </div>

        {/* Swing Desk */}
        <div className="glass-panel rounded-2xl p-4 border border-purple-500/20 bg-purple-950/20 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-black uppercase tracking-wider text-purple-300 flex items-center gap-1.5">
              🌊 Swing Desk (25%)
            </span>
            <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${swingSlots > 0 ? "bg-purple-500/30 text-purple-200 border-purple-400/50 font-bold" : "bg-purple-500/20 text-purple-300 border-purple-500/30"}`}>
              {swingSlots} / {swingDesk.max_slots ?? 1} Slot
            </span>
          </div>
          <div className="mt-2.5 flex items-baseline justify-between">
            <div>
              <p className="text-xl font-black text-white font-mono">${(swingDesk.allocated_usd ?? 250.0).toFixed(0)}</p>
              <p className="text-[10px] text-slate-400">1D (24H) Swing Trade Timeframe (2x Leverage)</p>
            </div>
            <div className="text-right">
              <span className={`text-xs font-bold font-mono ${swingPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {swingPnl >= 0 ? "+" : ""}${swingPnl.toFixed(2)}
              </span>
              <p className="text-[10px] text-slate-400">Tier-0 BE: +1.75%</p>
            </div>
          </div>
        </div>
      </div>

      {/* Main Open Positions Panel */}
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
                  <h3 className="text-base font-black text-white">Reset Institutional Paper Portfolio?</h3>
                  <p className="text-xs text-slate-400">Initialize a clean $1,000.00 multi-desk testing ledger</p>
                </div>
              </div>

              <p className="text-xs text-slate-300 leading-relaxed">
                Are you sure you want to reset paper trading? This will:
              </p>
              <ul className="text-xs text-slate-400 list-disc list-inside mt-2 space-y-1 font-mono">
                <li>Close &amp; archive all active open positions across all desks</li>
                <li>Wipe previous closed trade history and start fresh</li>
                <li>Reset wallet capital back to clean <span className="text-emerald-400 font-bold">$1,000.00</span></li>
                <li>Partition into 3 independent Desks (Scalp 35%, Day Trading 40%, Swing 25%)</li>
                <li>Enforce ATR Risk Parity (1.5% fixed portfolio risk per trade)</li>
                <li>Apply VIP0 Binance Futures taker fees &amp; 8H perpetual funding accounting</li>
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
                      Confirm Reset to $1,000.00
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
              💼 Active Open Positions
              <span className="rounded-md bg-emerald-950 px-2 py-0.5 text-xs font-semibold text-emerald-400 border border-emerald-800">
                {openPositions.length} / 5 Maximum Concurrent
              </span>
            </h2>
            <div className="flex flex-wrap items-center gap-3 mt-1 text-xs text-slate-400">
              <span>Sharpe: <strong className="text-white font-mono">{sharpe.toFixed(2)}</strong></span>
              <span>Sortino: <strong className="text-white font-mono">{sortino.toFixed(2)}</strong></span>
              <span>PF: <strong className="text-white font-mono">{profitFactor.toFixed(2)}</strong></span>
              <span>Expectancy: <strong className="text-emerald-400 font-mono">${expectancy.toFixed(2)}/tr</strong></span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setShowConfirmModal(true)}
              className="rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 px-3 py-1.5 text-xs font-semibold flex items-center gap-1.5 transition-all hover:border-rose-500/60 ml-auto"
              title="Wipe previous open positions and reset paper trading wallet to $1,000.00"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset Ledger ($1,000)
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
              The 3-Desk engine automatically opens virtual positions when institutional Grade A/A+ setups fire across Scalp (15M/30M), Day Trading (1H/4H), and Swing (1D) without cross-desk slot starvation.
            </p>
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {openPositions.map((pos: any) => {
              const isLong = pos.direction === "BULLISH" || pos.direction === "LONG";
              const uPnl = pos.unrealized_pnl_usd ?? 0.0;
              const uPct = pos.unrealized_pnl_pct ?? 0.0;
              const stage = pos.stage || "OPEN";
              const isBeLocked = stage.includes("BREAKEVEN") || pos.is_tier0_locked || pos.is_tp1_locked;
              const isTpLocked = stage.includes("TP") || pos.is_tp1_locked || pos.is_tp2_locked;

              // Active Target Escalation Resolution
              const activeTpLabel = pos.active_tp_level 
                ? `${pos.active_tp_level} Target` 
                : (pos.is_tp2_locked ? "TP3 Runner Target" : (pos.is_tp1_locked ? "TP2 Scaled Target" : "TP Target"));
              
              const activeTpPrice = pos.active_tp_price 
                || (pos.is_tp2_locked ? (pos.tp3_price || pos.tp_price) : (pos.is_tp1_locked ? (pos.tp2_price || pos.tp_price) : (pos.tp_price || pos.tp1_price)));

              const hasBankedProfit = (pos.realized_net_pnl && pos.realized_net_pnl > 0.01) || pos.is_tp1_locked;
              const activeNominal = pos.remaining_position_size_usd || pos.allocated_usd || pos.position_size_usd || 100;
              const isScaledRunner = pos.remaining_position_size_usd && pos.initial_position_size_usd && (pos.remaining_position_size_usd < pos.initial_position_size_usd * 0.95);

              return (
                <div
                  key={pos.trade_id || pos.id}
                  className="rounded-xl bg-dark-900/90 p-4 border border-slate-800/80 hover:border-slate-700 transition-all flex flex-col justify-between"
                >
                  <div>
                    {/* Top Bar: Symbol, Desk Badge, Direction */}
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5">
                          <h4 className="text-base font-black text-white">{pos.symbol}</h4>
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                            {pos.desk_name || pos.horizon}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5 text-[11px] text-slate-400 font-mono">
                          <span className="text-cyan-400">{pos.horizon}</span>
                          <span>•</span>
                          <span>{pos.leverage || 3}x Lev</span>
                          <span>•</span>
                          <span>${activeNominal.toFixed(0)} Nom</span>
                          {isScaledRunner && (
                            <span className="text-[10px] text-emerald-400 font-bold bg-emerald-950/60 px-1.5 py-0.2 rounded border border-emerald-800/60">
                              Runner Active
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-col items-end gap-1">
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
                        {isBeLocked && (
                          <span className="text-[9px] font-bold text-amber-300 px-1.5 py-0.2 rounded bg-amber-950/80 border border-amber-800/80">
                            🛡️ BE LOCKED
                          </span>
                        )}
                        {isTpLocked && (
                          <span className="text-[9px] font-bold text-emerald-300 px-1.5 py-0.2 rounded bg-emerald-950/80 border border-emerald-800/80">
                            🎯 {pos.active_tp_level ? `${pos.active_tp_level} ACTIVE` : "TP SCALED"}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Banked Profit Banner if TP was scaled */}
                    {hasBankedProfit && (
                      <div className="mt-2.5 flex items-center justify-between text-[11px] font-mono bg-emerald-950/50 border border-emerald-800/70 rounded-lg px-2.5 py-1.5 text-emerald-300 shadow-sm">
                        <span className="font-bold flex items-center gap-1.5 text-emerald-400">
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 animate-pulse" />
                          {pos.is_tp2_locked ? "TP1 & TP2 Banked:" : "TP1 Scaled & Banked:"}
                        </span>
                        <strong className="text-white font-black font-mono">
                          +{formatUsd(pos.realized_net_pnl || pos.tp1_banked_usd || 0.0)}
                        </strong>
                      </div>
                    )}

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
                        <span className="text-[10px] uppercase font-bold text-emerald-400 flex items-center gap-1">
                          {activeTpLabel}
                        </span>
                        <p className="text-emerald-400 font-bold">{formatUsd(activeTpPrice)}</p>
                      </div>
                      <div className="border-t border-slate-800/60 pt-1.5">
                        <span className="text-[10px] uppercase font-bold text-rose-400">
                          {isBeLocked ? "Stop-Loss (BE Locked)" : "Stop-Loss"}
                        </span>
                        <p className={isBeLocked ? "text-amber-300 font-bold" : "text-rose-400"}>{formatUsd(pos.sl_price)}</p>
                      </div>
                    </div>

                    {/* Trade Progress Bar */}
                    <TradeProgressBar
                      entryPrice={pos.entry_price}
                      currentPrice={pos.current_price}
                      tpPrice={activeTpPrice}
                      slPrice={pos.sl_price}
                      direction={pos.direction}
                      targetProgressPct={pos.target_progress_pct}
                      targetLabel={pos.active_tp_level || (pos.is_tp2_locked ? "TP3" : (pos.is_tp1_locked ? "TP2" : "TP"))}
                    />

                    {/* Extremes (MFE / MAE) */}
                    {(pos.mfe_pct !== undefined || pos.mae_pct !== undefined) && (
                      <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-slate-400 px-1">
                        <span>Peak Gain: <strong className="text-emerald-400">+{pos.mfe_pct ?? 0}%</strong></span>
                        <span>Max Drawdown: <strong className="text-rose-400">-{pos.mae_pct ?? 0}%</strong></span>
                      </div>
                    )}
                  </div>

                  {/* Bottom PnL & Fee Bar */}
                  <div className="mt-4 border-t border-slate-800/60 pt-2.5">
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-[10px] uppercase font-bold text-slate-400">VIP0 Fees:</span>
                        <span className="bg-dark-950 px-1.5 py-0.5 rounded border border-slate-800 text-slate-300">
                          -${((pos.buy_fee_usd ?? 0.01) + (pos.est_sell_fee_usd ?? 0.01)).toFixed(2)}
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
    </div>
  );
}
