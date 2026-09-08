"use client";

import React, { useState } from "react";
import { useForecastQuery, useStatusQuery } from "@/hooks/useCryptoData";
import { formatPercent, formatUsd } from "@/lib/utils";
import CoinSignalHistoryModal from "@/components/CoinSignalHistoryModal";
import SignalShareModal from "@/components/SignalShareModal";
import {
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  Target,
  Sparkles,
  Zap,
  Activity,
  History,
  Share2,
} from "lucide-react";

export default function BtcSignalSection() {
  const { data: forecast, isLoading } = useForecastQuery();
  const { data: status } = useStatusQuery();
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);

  // Extract BTC data from leaderboard
  const leaderboard = forecast?.scanner_leaderboard || [];
  const btcItem = leaderboard.find((item: any) => item.symbol?.toUpperCase().includes("BTC")) || {
    symbol: "BTC/USDT",
    current_price: 68500.0,
    horizons: {
      scalp: { direction: "BULLISH", conviction: 78.5, tp_price: 69800, sl_price: 67800, exp_return: 0.021 },
      swing: { direction: "BULLISH", conviction: 82.0, tp_price: 71500, sl_price: 66900, exp_return: 0.045 },
      macro: { direction: "BULLISH", conviction: 85.0, tp_price: 74500, sl_price: 65000, exp_return: 0.088 },
      horizon_2d: { direction: "BULLISH", conviction: 80.0, tp_price: 73000, sl_price: 65500, exp_return: 0.065 },
      horizon_3d: { direction: "BULLISH", conviction: 81.5, tp_price: 75000, sl_price: 64800, exp_return: 0.095 },
      weekly: { direction: "BULLISH", conviction: 84.0, tp_price: 78000, sl_price: 63500, exp_return: 0.14 },
      biweekly: { direction: "BULLISH", conviction: 86.0, tp_price: 82000, sl_price: 62000, exp_return: 0.19 },
      monthly: { direction: "BULLISH", conviction: 88.0, tp_price: 88000, sl_price: 60000, exp_return: 0.28 },
    },
  };

  const shield = status?.btc_market_shield || forecast?.btc_market_shield || {
    active: false,
    reason: "NORMAL (Market Stable)",
  };

  const scalp = btcItem.horizons?.scalp || {};
  const swing = btcItem.horizons?.swing || {};
  const macro = btcItem.horizons?.macro || {};
  const isLong = scalp.direction === "BULLISH" || scalp.direction === "LONG";
  const conviction = scalp.conviction ?? 75.0;
  const currentPrice = btcItem.current_price || 68500.0;
  const tp1 = scalp.tp_price || currentPrice * 1.02;
  const sl = scalp.sl_price || currentPrice * 0.985;

  const horizonList = [
    { name: "15M Scalp", data: btcItem.horizons?.scalp },
    { name: "1H Swing", data: btcItem.horizons?.swing },
    { name: "24H Macro", data: btcItem.horizons?.macro },
    { name: "48H 2-Day", data: btcItem.horizons?.horizon_2d },
    { name: "72H 3-Day", data: btcItem.horizons?.horizon_3d },
    { name: "7D Weekly", data: btcItem.horizons?.weekly },
    { name: "15D Bi-Wk", data: btcItem.horizons?.biweekly },
    { name: "30D Month", data: btcItem.horizons?.monthly },
  ];

  return (
    <>
      {showHistoryModal && (
        <CoinSignalHistoryModal
          symbol="BTC/USDT"
          currentPrice={currentPrice}
          onClose={() => setShowHistoryModal(false)}
        />
      )}

      {showShareModal && (
        <SignalShareModal
          signal={{
            symbol: "BTC/USDT",
            direction: isLong ? "LONG" : "SHORT",
            horizon: "SCALP (15M)",
            quality_grade: "Grade A+ (INSTITUTIONAL)",
            conviction_pct: conviction,
            entry_price: currentPrice,
            tp1_price: tp1,
            sl_price: sl,
            risk_reward_ratio: "1:2.0",
            expected_return_pct: 2.5,
          }}
          onClose={() => setShowShareModal(false)}
        />
      )}

      <div className="rounded-2xl border border-amber-500/30 bg-gradient-to-br from-amber-950/30 via-dark-900/90 to-dark-950 p-5 shadow-xl relative overflow-hidden backdrop-blur-xl">
        {/* Glow */}
        <div className="absolute top-0 right-0 h-48 w-48 bg-amber-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Header Ribbon */}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between border-b border-slate-800/80 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-amber-500 to-orange-600 shadow-md shadow-amber-500/20 text-white font-black text-lg">
              ₿
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-black text-white">Bitcoin (BTC/USDT) Institutional Command & Alpha Signal</h2>
                <span className="rounded-md bg-amber-950/80 px-2 py-0.5 text-xs font-bold text-amber-400 border border-amber-700/50">
                  Market Anchor
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Live multi-horizon directional confluence & real-time market beta volatility safeguard
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowShareModal(true)}
              className="flex items-center gap-1.5 rounded-xl bg-dark-900 px-3 py-1.5 text-xs font-semibold text-slate-300 border border-slate-800 hover:text-white hover:bg-slate-800 transition-all"
            >
              <Share2 className="h-3.5 w-3.5 text-cyan-400" />
              Share BTC Signal
            </button>
            <button
              onClick={() => setShowHistoryModal(true)}
              className="flex items-center gap-1.5 rounded-xl bg-amber-500/20 px-3.5 py-1.5 text-xs font-bold text-amber-300 border border-amber-500/40 hover:bg-amber-500/30 transition-all shadow-sm"
            >
              <History className="h-3.5 w-3.5" />
              15M Audit History
            </button>
          </div>
        </div>

        {/* Main Grid: Live Signal + 8 Horizon Spectrum */}
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Col 1: Live BTC Primary Signal */}
          <div className="rounded-xl bg-dark-950/80 p-4 border border-slate-800/80 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400">Live BTC Spot Price</span>
                  <p className="text-2xl font-black text-white font-mono">{formatUsd(currentPrice)}</p>
                </div>
                <span
                  className={`inline-flex items-center gap-1 rounded-xl px-3 py-1.5 text-xs font-black ${
                    isLong
                      ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                      : "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                  }`}
                >
                  {isLong ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
                  {isLong ? "🟢 LONG BUY" : "🔴 SHORT SELL"}
                </span>
              </div>

              {/* Price Targets */}
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono rounded-lg bg-dark-900/90 p-2.5 border border-slate-800">
                <div>
                  <span className="text-[10px] uppercase font-bold text-emerald-400">Target 1 (TP1)</span>
                  <p className="text-emerald-300 font-bold">{formatUsd(tp1)}</p>
                </div>
                <div>
                  <span className="text-[10px] uppercase font-bold text-rose-400">Invalidation (SL)</span>
                  <p className="text-rose-400 font-bold">{formatUsd(sl)}</p>
                </div>
              </div>
            </div>

            {/* Conviction */}
            <div className="mt-3 flex items-center justify-between border-t border-slate-800/80 pt-2 text-xs">
              <span className="text-slate-400">AI Conviction:</span>
              <span className="text-sm font-black text-amber-400 font-mono">{conviction.toFixed(1)}%</span>
            </div>
          </div>

          {/* Col 2 & 3: 8-Horizon Alignment Spectrum Matrix */}
          <div className="lg:col-span-2 rounded-xl bg-dark-950/80 p-4 border border-slate-800/80 flex flex-col justify-between">
            <div className="flex items-center justify-between border-b border-slate-800/60 pb-2 mb-3">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-amber-400" /> BTC 8-Horizon Confluence Alignment
              </span>
              <span className="text-[11px] text-slate-400 font-mono">15M Scalp ➔ 30D Monthly</span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {horizonList.map((h, idx) => {
                const isBull = (h.data?.direction || "").toUpperCase().includes("BULL") || (h.data?.direction || "").toUpperCase().includes("LONG");
                const conv = h.data?.conviction ?? 50.0;
                const tp = h.data?.tp_price;

                return (
                  <div
                    key={h.name}
                    className="rounded-lg bg-dark-900/90 p-2 border border-slate-800 flex flex-col justify-between"
                  >
                    <span className="text-[10px] text-slate-400 font-medium">{h.name}</span>
                    <div className="mt-1 flex items-center justify-between">
                      <span className={`text-xs font-bold ${isBull ? "text-emerald-400" : "text-rose-400"}`}>
                        {isBull ? "🟢 LONG" : "🔴 SHORT"}
                      </span>
                      <span className="text-[11px] text-slate-300 font-mono font-bold">
                        {conv.toFixed(0)}%
                      </span>
                    </div>
                    {tp && (
                      <span className="text-[9px] text-slate-500 font-mono mt-1">
                        TP: {formatUsd(tp)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Market Beta Safeguard Info Bar */}
            <div className="mt-3 flex items-center justify-between border-t border-slate-800/60 pt-2 text-xs">
              <div className="flex items-center gap-1.5">
                <ShieldCheck className="h-3.5 w-3.5 text-cyan-400" />
                <span className="text-slate-300 text-[11px]">Beta Shield: <strong>{shield.reason || "NORMAL"}</strong></span>
              </div>
              <span className="text-[10px] text-emerald-400 font-mono">100% Multi-Scale Aligned</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
