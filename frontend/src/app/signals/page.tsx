"use client";

import React, { useState } from "react";
import KpiMetrics from "@/components/KpiMetrics";
import DailySignalsView from "@/components/DailySignalsView";
import SignalsTable from "@/components/SignalsTable";

export default function SignalsPage() {
  const [selectedDate, setSelectedDate] = useState<string>("");

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-black tracking-tight text-white">
          Trader Signals Audit Ledger
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Complete historical and live signals presented to traders with real-time target evaluations, invalidation points, and win/loss audit tracking.
        </p>
      </div>

      <KpiMetrics />

      <DailySignalsView
        selectedDate={selectedDate}
        onSelectDate={(d) => setSelectedDate(d)}
      />

      <SignalsTable initialDate={selectedDate} key={selectedDate} />
    </div>
  );
}
