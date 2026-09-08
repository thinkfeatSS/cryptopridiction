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
          Automated paper trading on $15.00 virtual capital (max 3 concurrent positions @ $5.00 each, min $0.80 net profit filter in Spot &amp; positive win/loss track record).
        </p>
      </div>

      <KpiMetrics />

      <PortfolioView />

      <QueuedTrades />

      <ClosedTrades />
    </div>
  );
}
