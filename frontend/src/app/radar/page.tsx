"use client";

import React, { useState } from "react";
import KpiMetrics from "@/components/KpiMetrics";
import AssetPredictionMatrix from "@/components/AssetPredictionMatrix";
import RadarTable from "@/components/RadarTable";
import StarredRadarTable from "@/components/StarredRadarTable";
import { useWatchlist } from "@/hooks/useWatchlist";
import { Star, Radar, Layers } from "lucide-react";

export default function RadarPage() {
  const { watchlist } = useWatchlist();
  const [activeTab, setActiveTab] = useState<"starred" | "all">(
    watchlist.length > 0 ? "starred" : "all"
  );

  return (
    <div className="space-y-8">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-white">
            Multi-Horizon Opportunity Matrix & Active Trades Radar
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Simultaneous multi-scale scanning across Scalp (15M), Swing (1H-2H), and Macro (24H) horizons with active trade monitoring.
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center gap-1.5 rounded-xl bg-dark-950 p-1.5 border border-slate-800 self-start md:self-auto">
          <button
            onClick={() => setActiveTab("starred")}
            className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-bold transition-all ${
              activeTab === "starred"
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/50 shadow-sm"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Star className={`h-3.5 w-3.5 ${activeTab === "starred" ? "fill-amber-400 text-amber-400" : ""}`} />
            <span>Starred Active Trades ({watchlist.length})</span>
          </button>
          <button
            onClick={() => setActiveTab("all")}
            className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-bold transition-all ${
              activeTab === "all"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Radar className="h-3.5 w-3.5" />
            <span>All 100 Assets Radar</span>
          </button>
        </div>
      </div>

      <KpiMetrics />

      {activeTab === "starred" ? (
        <div className="space-y-8">
          <StarredRadarTable />
          <AssetPredictionMatrix />
        </div>
      ) : (
        <div className="space-y-8">
          <RadarTable />
          <AssetPredictionMatrix />
        </div>
      )}
    </div>
  );
}

