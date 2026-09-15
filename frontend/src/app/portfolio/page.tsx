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
          Automated paper trading on $100.00 margin per trade (min $20.00 net profit hurdle with 100% real Binance Spot fee deductions: 0.10% buy fee &amp; 0.10% sell fee).
        </p>
      </div>

      <KpiMetrics />

      <PortfolioView />

      <QueuedTrades />

      <ClosedTrades />
    </div>
  );
}
