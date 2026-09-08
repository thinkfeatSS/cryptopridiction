"use client";

import React from "react";
import { useStatusQuery, useForecastQuery } from "@/hooks/useCryptoData";
import { Shield, ShieldAlert, ShieldCheck, Zap, Activity, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";
import { getShieldTheme } from "@/lib/marketShield";

export default function MarketShieldBanner() {
  const { data: status } = useStatusQuery();
  const { data: forecast } = useForecastQuery();

  const shield = status?.btc_market_shield || forecast?.btc_market_shield || {
    active: false,
    status_code: "NORMAL",
    reason: "NORMAL (Market Stable)",
  };

  const theme = getShieldTheme(shield);
  const btc15m = shield.btc_15m_change_pct;
  const btc1h = shield.btc_1h_change_pct;

  return (
    <div
      className={`rounded-2xl border p-4 sm:p-5 transition-all relative overflow-hidden backdrop-blur-xl ${
        shield.active
          ? "border-rose-500/60 bg-gradient-to-r from-rose-950/40 via-dark-900/90 to-red-950/30 shadow-lg shadow-rose-500/10"
          : theme.label === "CAUTION"
          ? "border-amber-500/60 bg-gradient-to-r from-amber-950/40 via-dark-900/90 to-orange-950/20 shadow-lg shadow-amber-500/10"
          : theme.label === "BULLISH EXPANSION"
          ? "border-emerald-500/50 bg-gradient-to-r from-emerald-950/30 via-dark-900/90 to-indigo-950/20 shadow-lg shadow-emerald-500/10"
          : "border-cyan-500/30 bg-gradient-to-r from-cyan-950/30 via-dark-900/90 to-indigo-950/20 shadow-lg shadow-cyan-500/5"
      }`}
    >
      {/* Background ambient glow */}
      <div
        className={`absolute -top-10 -right-10 h-36 w-36 rounded-full blur-3xl pointer-events-none ${theme.glowBg}`}
      />

      <div className="flex flex-col gap-3.5 sm:flex-row sm:items-center sm:justify-between relative z-10">
        {/* Left Section: Icon & Main Status */}
        <div className="flex items-start sm:items-center gap-3.5">
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border shadow-inner ${
              theme.isAlert
                ? "border-rose-400/60 bg-rose-500/20 text-rose-300 shadow-rose-500/30 animate-pulse"
                : theme.label === "CAUTION"
                ? "border-amber-400/50 bg-amber-500/15 text-amber-300"
                : theme.label === "BULLISH EXPANSION"
                ? "border-emerald-400/50 bg-emerald-500/15 text-emerald-300"
                : "border-cyan-400/40 bg-cyan-500/10 text-cyan-300 shadow-cyan-500/20"
            }`}
          >
            {theme.isAlert ? (
              <ShieldAlert className="h-6 w-6 text-rose-400" />
            ) : theme.label === "CAUTION" ? (
              <AlertTriangle className="h-6 w-6 text-amber-400" />
            ) : (
              <ShieldCheck className={`h-6 w-6 ${theme.iconColor}`} />
            )}
          </div>

          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-1.5 font-mono">
                [SHIELD 🛡️] Market Beta Status:
              </span>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-black uppercase tracking-wide border ${theme.badgeBg}`}
              >
                <span className="relative flex h-2 w-2">
                  <span
                    className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${theme.pingColor}`}
                  ></span>
                  <span
                    className={`relative inline-flex h-2 w-2 rounded-full ${theme.dotColor}`}
                  ></span>
                </span>
                {theme.statusTitle}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              {theme.subline}
            </p>
          </div>
        </div>

        {/* Right Section: Quant Safeguard Tags & Live Metric Chips */}
        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto shrink-0">
          {btc15m !== undefined && (
            <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">BTC 15M:</span>
              <span className={`font-bold flex items-center ${btc15m >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {btc15m >= 0 ? <TrendingUp className="h-3 w-3 mr-0.5 inline" /> : <TrendingDown className="h-3 w-3 mr-0.5 inline" />}
                {btc15m > 0 ? `+${btc15m}%` : `${btc15m}%`}
              </span>
            </div>
          )}
          {btc1h !== undefined && (
            <div className="hidden sm:flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
              <span className="text-slate-400">BTC 1H:</span>
              <span className={`font-bold flex items-center ${btc1h >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {btc1h >= 0 ? <TrendingUp className="h-3 w-3 mr-0.5 inline" /> : <TrendingDown className="h-3 w-3 mr-0.5 inline" />}
                {btc1h > 0 ? `+${btc1h}%` : `${btc1h}%`}
              </span>
            </div>
          )}
          <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
            <Activity className="h-3.5 w-3.5 text-cyan-400" />
            <span>BTC Beta Filter: <strong className="text-white">Live Active</strong></span>
          </div>
          <div className="hidden md:flex items-center gap-1.5 rounded-lg border border-slate-800 bg-dark-950/80 px-2.5 py-1 text-[11px] text-slate-300 font-mono">
            <Zap className="h-3.5 w-3.5 text-indigo-400" />
            <span>Corr SL Guard: <strong className={shield.active ? "text-rose-400" : "text-emerald-400"}>{shield.active ? "Enforcing" : "Armed"}</strong></span>
          </div>
        </div>
      </div>
    </div>
  );
}

