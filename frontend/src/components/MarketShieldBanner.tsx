"use client";

import React from "react";
import { useStatusQuery, useForecastQuery } from "@/hooks/useCryptoData";
import { Shield, ShieldAlert, ShieldCheck, Zap, Activity, Info } from "lucide-react";

export default function MarketShieldBanner() {
  const { data: status } = useStatusQuery();
  const { data: forecast } = useForecastQuery();

  const shield = status?.btc_market_shield || forecast?.btc_market_shield || {
    active: false,
    reason: "NORMAL (Market Stable)",
  };

  const isActive = shield.active;
  const reason = shield.reason || (isActive ? "BTC Flash Dump Detected" : "NORMAL (Market Stable)");

  return (
    <div
      className={`rounded-2xl border p-4 sm:p-5 transition-all relative overflow-hidden backdrop-blur-xl ${
        isActive
          ? "border-amber-500/60 bg-gradient-to-r from-amber-950/40 via-dark-900/90 to-red-950/30 shadow-lg shadow-amber-500/10"
          : "border-cyan-500/30 bg-gradient-to-r from-cyan-950/30 via-dark-900/90 to-indigo-950/20 shadow-lg shadow-cyan-500/5"
      }`}
    >
      {/* Background ambient glow */}
      <div
        className={`absolute -top-10 -right-10 h-32 w-32 rounded-full blur-3xl pointer-events-none ${
          isActive ? "bg-amber-500/20" : "bg-cyan-500/10"
        }`}
      />

      <div className="flex flex-col gap-3.5 sm:flex-row sm:items-center sm:justify-between relative z-10">
        {/* Left Section: Icon & Main Status */}
        <div className="flex items-start sm:items-center gap-3.5">
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border shadow-inner ${
              isActive
                ? "border-amber-400/60 bg-amber-500/20 text-amber-300 shadow-amber-500/30 animate-pulse"
                : "border-cyan-400/40 bg-cyan-500/10 text-cyan-300 shadow-cyan-500/20"
            }`}
          >
            {isActive ? (
              <ShieldAlert className="h-6 w-6 text-amber-400" />
            ) : (
              <Shield className="h-6 w-6 text-cyan-400" />
            )}
          </div>

          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5 font-mono">
                [SHIELD 🛡️] Market Beta Status:
              </span>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-black uppercase tracking-wide border ${
                  isActive
                    ? "bg-amber-500/20 text-amber-300 border-amber-500/50 shadow-sm shadow-amber-500/20 animate-pulse"
                    : "bg-emerald-500/15 text-emerald-300 border-emerald-500/40 shadow-sm shadow-emerald-500/10"
                }`}
              >
                <span className="relative flex h-2 w-2">
                  <span
                    className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${
                      isActive ? "bg-amber-400" : "bg-emerald-400"
                    }`}
                  ></span>
                  <span
                    className={`relative inline-flex h-2 w-2 rounded-full ${
                      isActive ? "bg-amber-500" : "bg-emerald-500"
                    }`}
                  ></span>
                </span>
                {reason}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              {isActive
                ? "⚠️ BTC Market Beta Circuit Breaker is active. Altcoin Long executions are temporarily paused to prevent correlated cascade stop-outs."
                : "🛡️ Real-time Cross-Asset Safeguard Active — BTC 15M/1H volatility is stable. Full multi-horizon entries permitted."}
            </p>
          </div>
        </div>

        {/* Right Section: Quant Safeguard Tags */}
        <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
          <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
            <Activity className="h-3.5 w-3.5 text-cyan-400" />
            <span>BTC Beta Filter: <strong className="text-white">Live Active</strong></span>
          </div>
          <div className="hidden md:flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
            <Zap className="h-3.5 w-3.5 text-indigo-400" />
            <span>Corr Stop-Loss Guard: <strong className="text-emerald-400">Armed</strong></span>
          </div>
        </div>
      </div>
    </div>
  );
}
