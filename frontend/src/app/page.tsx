"use client";

import React, { useState } from "react";
import KpiMetrics from "@/components/KpiMetrics";
import MarketShieldBanner from "@/components/MarketShieldBanner";
import AssetPredictionMatrix from "@/components/AssetPredictionMatrix";
import DailySignalsView from "@/components/DailySignalsView";
import SignalCard from "@/components/SignalCard";
import SignalsTable from "@/components/SignalsTable";
import PortfolioView from "@/components/PortfolioView";
import RadarTable from "@/components/RadarTable";
import { useForecastQuery } from "@/hooks/useCryptoData";
import { Sparkles, Zap, ShieldCheck, Layers, Calendar } from "lucide-react";

export default function DashboardPage() {
  const { data: forecast, isLoading } = useForecastQuery();
  const [selectedDate, setSelectedDate] = useState<string>("");

  const topSignals = forecast?.top_round_signals || [];

  return (
    <div className="space-y-8">
      {/* 0. Real-time Market Beta Shield Status Banner */}
      <section>
        <MarketShieldBanner />
      </section>

      {/* 1. Executive KPI Summary Ribbon */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
            <ShieldCheck className="h-4 w-4 text-cyan-400" /> Executive Performance KPI Overview
          </h2>
          <span className="text-[11px] text-slate-500 font-mono">
            Auto-Syncing with MySQL Database
          </span>
        </div>
        <KpiMetrics />
      </section>

      {/* 2. Complete 25-Asset Prediction Table & 15-Minute Refresh Countdown */}
      <section>
        <AssetPredictionMatrix />
      </section>

      {/* 3. Daily Signal Breakdown (Won / Lost / Return per Day) */}
      <section>
        <DailySignalsView
          selectedDate={selectedDate}
          onSelectDate={(d) => setSelectedDate(d)}
        />
      </section>

      {/* 4. Live Actionable Top Setup Cards (Grade A+ / A) */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-base font-black tracking-tight text-white flex items-center gap-2">
              <Zap className="h-5 w-5 text-cyan-400" />
              Institutional Setup Cards ({topSignals.length} Active This Round)
            </h2>
            <p className="text-xs text-slate-400">
              Highest-edge Grade A+ / Grade A opportunities evaluated on the current 15-minute candle
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="py-12 text-center text-xs text-slate-500 font-mono glass-panel rounded-2xl">
            Loading institutional setup cards...
          </div>
        ) : topSignals.length === 0 ? (
          <div className="glass-panel rounded-2xl p-8 text-center text-slate-400">
            <h3 className="text-sm font-bold text-white">No Grade A+ Setups Firing Right Now</h3>
            <p className="text-xs text-slate-400 mt-1">
              Market is in defensive mode. Next full scan will evaluate new entries on the 15-minute mark.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {topSignals.map((sig: any, idx: number) => (
              <SignalCard key={sig.signal_id || idx} signal={sig} rankIndex={idx} />
            ))}
          </div>
        )}
      </section>

      {/* 5. Active Open Paper Positions */}
      <section>
        <PortfolioView />
      </section>

      {/* 6. Complete Verifiable Signals Audit Table */}
      <section>
        <SignalsTable initialDate={selectedDate} key={selectedDate} />
      </section>

      {/* 7. Multi-Horizon Opportunity Leaderboard */}
      <section>
        <RadarTable />
      </section>
    </div>
  );
}
