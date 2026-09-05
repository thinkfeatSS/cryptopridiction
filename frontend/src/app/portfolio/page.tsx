"use client";

import React from "react";
import KpiMetrics from "@/components/KpiMetrics";
import PortfolioView from "@/components/PortfolioView";
import ClosedTrades from "@/components/ClosedTrades";

export default function PortfolioPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-black tracking-tight text-white">
          Active Paper Trading Bot & Ledger
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Automated paper trading execution across $10k virtual capital with real-time Take-Profit / Stop-Loss tracking and Binance fee simulation.
        </p>
      </div>

      <KpiMetrics />

      <PortfolioView />

      <ClosedTrades />
    </div>
  );
}
