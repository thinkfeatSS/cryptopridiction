"use client";

import React, { useState, useMemo } from "react";
import { useCoinSignalsQuery } from "@/hooks/useCryptoData";
import { formatUsd, formatPercent } from "@/lib/utils";
import { useWatchlist } from "@/hooks/useWatchlist";
import TradingViewCandleChart from "@/components/TradingViewCandleChart";
import SignalShareModal from "@/components/SignalShareModal";
import {
  X,
  Clock,
  TrendingUp,
  TrendingDown,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Hourglass,
  ArrowUpRight,
  ArrowDownRight,
  Sparkles,
  Zap,
  Star,
  Share2,
} from "lucide-react";

interface CoinSignalHistoryModalProps {
  symbol: string | null;
  currentPrice?: number;
  onClose: () => void;
}

export default function CoinSignalHistoryModal({
  symbol,
  currentPrice = 0,
  onClose,
}: CoinSignalHistoryModalProps) {
  const [outcomeFilter, setOutcomeFilter] = useState<string>("ALL");
  const [horizonFilter, setHorizonFilter] = useState<string>("ALL");
  const [sharingSignal, setSharingSignal] = useState<any | null>(null);

  const { isStarred, toggleWatchlist } = useWatchlist();
  const { data: signals = [], isLoading } = useCoinSignalsQuery(symbol || undefined);

  if (!symbol) return null;

  const starred = isStarred(symbol);
  const latestSignal = signals.length > 0 ? signals[0] : null;

  // Memoize filtered signals
  const filteredSignals = useMemo(() => {
    return signals.filter((sig) => {
      if (outcomeFilter !== "ALL") {
        const outcome = (sig.outcome_label || sig.status || "").toUpperCase();
        if (outcomeFilter === "WON" && !outcome.includes("WON")) return false;
        if (outcomeFilter === "LOST" && !outcome.includes("LOST")) return false;
        if (outcomeFilter === "PENDING" && !outcome.includes("PENDING")) return false;
      }
      if (horizonFilter !== "ALL") {
        const h = (sig.horizon || "").toUpperCase();
        if (!h.includes(horizonFilter.toUpperCase())) return false;
      }
      return true;
    });
  }, [signals, outcomeFilter, horizonFilter]);

  // Memoize Coin-level stats
  const { total, wonCount, lostCount, pendingCount, winRate } = useMemo(() => {
    const tot = signals.length;
    const won = signals.filter((s) => (s.outcome_label || s.status || "").toUpperCase().includes("WON")).length;
    const lost = signals.filter((s) => (s.outcome_label || s.status || "").toUpperCase().includes("LOST")).length;
    const pending = signals.filter((s) => (s.outcome_label || s.status || "").toUpperCase().includes("PENDING")).length;
    const decisive = won + lost;
    const wr = decisive > 0 ? ((won / decisive) * 100).toFixed(1) : "0.0";
    return { total: tot, wonCount: won, lostCount: lost, pendingCount: pending, winRate: wr };
  }, [signals]);

  const getOutcomeBadge = (sig: any) => {
    const outcomeStr = (sig.outcome_label || sig.status || "").toUpperCase();
    if (outcomeStr.includes("WON")) {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-950/80 px-2.5 py-1 text-xs font-bold text-emerald-400 border border-emerald-500/50 shadow-sm shadow-emerald-500/20">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
          {sig.outcome_label || "WON 🟢"}
        </span>
      );
    }
    if (outcomeStr.includes("LOST")) {
      return (
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-rose-950/80 px-2.5 py-1 text-xs font-bold text-rose-400 border border-rose-500/50 shadow-sm shadow-rose-500/20">
          <XCircle className="h-3.5 w-3.5 text-rose-400" />
          {sig.outcome_label || "LOST 🔴"}
        </span>
      );
    }
    // Pending signal in required BLUE color
    return (
      <span className="inline-flex items-center gap-1.5 rounded-lg bg-blue-950/80 px-2.5 py-1 text-xs font-bold text-blue-400 border border-blue-500/50 shadow-sm shadow-blue-500/20">
        <Hourglass className="h-3.5 w-3.5 text-blue-400 animate-pulse" />
        {sig.outcome_label || "PENDING ⏳"}
      </span>
    );
  };

  return (
    <>
      {/* Share Ticket Card Modal */}
      {sharingSignal && (
        <SignalShareModal signal={sharingSignal} onClose={() => setSharingSignal(null)} />
      )}

      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-3 sm:p-6 animate-in fade-in duration-200">
        <div className="relative w-full max-w-6xl max-h-[92vh] flex flex-col rounded-2xl bg-dark-950 border border-slate-800 shadow-2xl shadow-cyan-500/10 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-800/80 px-6 py-4 bg-dark-900/80">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-950 border border-cyan-700/50 text-cyan-400">
                  <Zap className="h-5 w-5" />
                </span>
                <div>
                  <div className="flex items-center gap-2.5">
                    <h2 className="text-xl font-black text-white">{symbol}</h2>
                    <button
                      onClick={() => toggleWatchlist(symbol)}
                      className={`p-1 rounded-lg border transition-all ${
                        starred
                          ? "bg-amber-500/20 border-amber-500/50 text-amber-400"
                          : "bg-dark-900 border-slate-800 text-slate-500 hover:text-amber-400"
                      }`}
                      title={starred ? "Remove from Watchlist" : "Add to Watchlist"}
                    >
                      <Star className={`h-4 w-4 ${starred ? "fill-amber-400 text-amber-400" : ""}`} />
                    </button>
                    {currentPrice ? (
                      <span className="font-mono text-sm font-bold text-cyan-400">
                        {formatUsd(currentPrice)}
                      </span>
                    ) : null}
                  </div>
                  <p className="text-xs text-slate-400">
                    Chronological 15-Minute Signal History & Real-Time Performance Audit
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {latestSignal && (
                <button
                  onClick={() => setSharingSignal({ ...latestSignal, symbol, current_price: currentPrice })}
                  className="flex items-center gap-1.5 rounded-xl bg-cyan-950/80 px-3 py-1.5 text-xs font-semibold text-cyan-300 border border-cyan-700/60 hover:bg-cyan-900 transition-colors shadow-sm"
                >
                  <Share2 className="h-3.5 w-3.5" />
                  Share Signal
                </button>
              )}
              <button
                onClick={onClose}
                className="rounded-xl p-2 text-slate-400 hover:text-white hover:bg-slate-800/80 transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>

          {/* Body with Scroll */}
          <div className="flex-1 overflow-y-auto">
            {/* 1. Interactive TradingView Candlestick Chart */}
            <div className="p-4 sm:p-6 pb-2">
              <TradingViewCandleChart
                symbol={symbol}
                currentPrice={currentPrice}
                entryPrice={latestSignal?.entry_price}
                tp1Price={latestSignal?.tp1_price}
                tp2Price={latestSignal?.tp2_price}
                tp3Price={latestSignal?.tp3_price}
                slPrice={latestSignal?.sl_price}
                direction={latestSignal?.direction || "LONG"}
              />
            </div>

            {/* 2. Stats Ribbon */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 p-4 sm:px-6 bg-dark-900/40 border-y border-slate-800">
              <div className="rounded-xl bg-dark-900/80 p-3 border border-slate-800">
                <span className="text-[10px] uppercase font-bold text-slate-400">Total Signals</span>
                <p className="text-lg font-black text-white">{total}</p>
              </div>
              <div className="rounded-xl bg-emerald-950/30 p-3 border border-emerald-500/30">
                <span className="text-[10px] uppercase font-bold text-emerald-400">Won (Green)</span>
                <p className="text-lg font-black text-emerald-400">{wonCount}</p>
              </div>
              <div className="rounded-xl bg-rose-950/30 p-3 border border-rose-500/30">
                <span className="text-[10px] uppercase font-bold text-rose-400">Lost (Red)</span>
                <p className="text-lg font-black text-rose-400">{lostCount}</p>
              </div>
              <div className="rounded-xl bg-blue-950/30 p-3 border border-blue-500/30">
                <span className="text-[10px] uppercase font-bold text-blue-400">Pending (Blue)</span>
                <p className="text-lg font-black text-blue-400">{pendingCount}</p>
              </div>
              <div className="rounded-xl bg-dark-900/80 p-3 border border-slate-800 col-span-2 sm:col-span-1">
                <span className="text-[10px] uppercase font-bold text-cyan-400">Win Rate</span>
                <p className="text-lg font-black text-white">{winRate}%</p>
              </div>
            </div>

            {/* 3. Filter Controls */}
            <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3 bg-dark-950 border-b border-slate-800">
              {/* Outcome Filter Buttons */}
              <div className="flex items-center gap-1.5 overflow-x-auto py-1">
                <button
                  onClick={() => setOutcomeFilter("ALL")}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition-all ${
                    outcomeFilter === "ALL"
                      ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  All Outcomes ({total})
                </button>
                <button
                  onClick={() => setOutcomeFilter("WON")}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition-all ${
                    outcomeFilter === "WON"
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      : "text-slate-400 hover:text-emerald-400"
                  }`}
                >
                  🟢 Won ({wonCount})
                </button>
                <button
                  onClick={() => setOutcomeFilter("LOST")}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition-all ${
                    outcomeFilter === "LOST"
                      ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                      : "text-slate-400 hover:text-rose-400"
                  }`}
                >
                  🔴 Lost ({lostCount})
                </button>
                <button
                  onClick={() => setOutcomeFilter("PENDING")}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition-all ${
                    outcomeFilter === "PENDING"
                      ? "bg-blue-500/20 text-blue-300 border border-blue-500/40"
                      : "text-slate-400 hover:text-blue-400"
                  }`}
                >
                  ⏳ Pending ({pendingCount})
                </button>
              </div>

              {/* Horizon Dropdown Filter */}
              <select
                value={horizonFilter}
                onChange={(e) => setHorizonFilter(e.target.value)}
                className="rounded-xl bg-dark-900 px-3 py-1.5 text-xs text-slate-300 border border-slate-800 focus:border-cyan-500 focus:outline-none font-mono"
              >
                <option value="ALL">⏱️ All Horizons</option>
                <option value="SCALP">⚡ Scalp (15M)</option>
                <option value="SWING">🌊 Swing (1H-2H)</option>
                <option value="MACRO">🚀 Macro (24H)</option>
                <option value="2-DAY">🔮 2-Day (48H)</option>
                <option value="3-DAY">🔭 3-Day (72H)</option>
                <option value="WEEKLY">🗓️ Weekly (7D)</option>
                <option value="BI-WEEKLY">🌕 Bi-Weekly (15D)</option>
                <option value="MONTHLY">🪐 Monthly (30D)</option>
              </select>
            </div>

            {/* 4. Signals Table */}
            <div className="p-4 sm:p-6">
              {isLoading ? (
                <div className="py-16 text-center text-xs text-slate-500 font-mono">
                  Loading 15-minute historical signals for {symbol}...
                </div>
              ) : filteredSignals.length === 0 ? (
                <div className="py-16 text-center text-slate-500 font-sans text-xs">
                  No signal records found matching the selected filters.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-slate-800/80">
                  <table className="w-full text-left text-xs text-slate-300 font-mono">
                    <thead className="bg-dark-900/90 uppercase text-[10px] font-bold tracking-wider text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="py-3 px-4">Date / Time (UTC)</th>
                        <th className="py-3 px-4">Horizon</th>
                        <th className="py-3 px-4">Direction & Conviction</th>
                        <th className="py-3 px-4">Entry Price</th>
                        <th className="py-3 px-4">Target (TP1) & SL</th>
                        <th className="py-3 px-4">Outcome Status</th>
                        <th className="py-3 px-4 text-right">Share / Return</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 bg-dark-950/40">
                      {filteredSignals.map((sig: any) => {
                        const isLong = sig.direction === "LONG" || sig.direction === "BULLISH";
                        const outcomeStr = (sig.outcome_label || sig.status || "").toUpperCase();
                        const isWon = outcomeStr.includes("WON");
                        const isLost = outcomeStr.includes("LOST");
                        const isPending = outcomeStr.includes("PENDING");

                        return (
                          <tr
                            key={sig.signal_id || sig.id}
                            className={`transition-colors ${
                              isWon
                                ? "hover:bg-emerald-950/20"
                                : isLost
                                ? "hover:bg-rose-950/20"
                                : "hover:bg-blue-950/20"
                            }`}
                          >
                            {/* Date & Time */}
                            <td className="py-3 px-4">
                              <div className="flex flex-col">
                                <span className="font-bold text-white font-sans">{sig.date_utc}</span>
                                <span className="text-[11px] text-slate-400">{sig.time_utc}</span>
                                <span className="text-[9px] text-slate-500">{sig.signal_id}</span>
                              </div>
                            </td>

                            {/* Horizon */}
                            <td className="py-3 px-4 font-sans">
                              <span className="rounded-md bg-dark-900 px-2 py-0.5 text-xs font-semibold text-cyan-300 border border-slate-800">
                                {sig.horizon}
                              </span>
                            </td>

                            {/* Direction & Conviction */}
                            <td className="py-3 px-4">
                              <div className="flex items-center gap-1.5">
                                <span
                                  className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-bold font-sans ${
                                    isLong
                                      ? "bg-emerald-500/20 text-emerald-400"
                                      : "bg-rose-500/20 text-rose-400"
                                  }`}
                                >
                                  {isLong ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                                  {sig.direction}
                                </span>
                                <span className="text-slate-300 font-bold">
                                  {sig.conviction_pct?.toFixed(1)}%
                                </span>
                              </div>
                            </td>

                            {/* Entry */}
                            <td className="py-3 px-4 font-bold text-white">
                              {formatUsd(sig.entry_price)}
                            </td>

                            {/* Targets */}
                            <td className="py-3 px-4">
                              <div className="flex flex-col text-[11px]">
                                <span className="text-emerald-400">TP1: {formatUsd(sig.tp1_price)}</span>
                                <span className="text-rose-400">SL: {formatUsd(sig.sl_price)}</span>
                              </div>
                            </td>

                            {/* Outcome Status (Blue/Green/Red) */}
                            <td className="py-3 px-4">
                              {getOutcomeBadge(sig)}
                            </td>

                            {/* Share / Realized Return */}
                            <td className="py-3 px-4 text-right">
                              <div className="flex items-center justify-end gap-2">
                                <button
                                  onClick={() => setSharingSignal({ ...sig, symbol, current_price: currentPrice })}
                                  className="p-1 rounded-lg text-slate-500 hover:text-cyan-400 hover:bg-slate-800 transition-colors"
                                  title="Export Signal Ticket"
                                >
                                  <Share2 className="h-3.5 w-3.5" />
                                </button>
                                {sig.realized_return_pct ? (
                                  <span
                                    className={`font-bold ${
                                      sig.realized_return_pct.startsWith("+")
                                        ? "text-emerald-400"
                                        : "text-rose-400"
                                    }`}
                                  >
                                    {sig.realized_return_pct}
                                  </span>
                                ) : isPending ? (
                                  <span className="text-blue-400 font-sans text-xs">Active ⏳</span>
                                ) : (
                                  <span className="text-slate-500">-</span>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
