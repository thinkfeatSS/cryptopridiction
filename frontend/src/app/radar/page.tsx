"use client";

import React from "react";
import KpiMetrics from "@/components/KpiMetrics";
import AssetPredictionMatrix from "@/components/AssetPredictionMatrix";
import RadarTable from "@/components/RadarTable";

export default function RadarPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-black tracking-tight text-white">
          Multi-Horizon Opportunity Matrix
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Simultaneous multi-scale scanning across Scalp (15M), Swing (1H-2H), and Macro (24H) horizons with Triple Confluence detection across 25 crypto assets.
        </p>
      </div>

      <KpiMetrics />

      <AssetPredictionMatrix />

      <RadarTable />
    </div>
  );
}
