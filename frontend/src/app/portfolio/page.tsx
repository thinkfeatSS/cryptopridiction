"use client";

import React from "react";
import KpiMetrics from "@/components/KpiMetrics";
import PortfolioView from "@/components/PortfolioView";
import QueuedTrades from "@/components/QueuedTrades";
import ClosedTrades from "@/components/ClosedTrades";

export default function PortfolioPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-black tracking-tight text-white">
          Active Paper Trading Bot & Ledger
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Automated paper trading on $100.00 margin per trade across 3 desks (5x Scalp, 3x Day, 2x Swing) with itemized Binance Futures fee (0.0405% taker with BNB discount), spread, slippage, and funding rate drag deductions.
        </p>
      </div>

      <KpiMetrics />

      <PortfolioView />

      <QueuedTrades />

      <ClosedTrades />
    </div>
  );
}
