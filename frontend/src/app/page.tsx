"use client";

import React, { useState, useMemo } from "react";
import V16Dashboard from "@/components/v16/V16Dashboard";
import KpiMetrics from "@/components/KpiMetrics";
import BtcSignalSection from "@/components/BtcSignalSection";
import TraderRegimePlaybookComponent from "@/components/TraderRegimePlaybook";
import SignalCard from "@/components/SignalCard";
import AssetPredictionMatrix from "@/components/AssetPredictionMatrix";
import DailySignalsView from "@/components/DailySignalsView";
import SignalsTable from "@/components/SignalsTable";
import PortfolioView from "@/components/PortfolioView";
import QueuedTrades from "@/components/QueuedTrades";
import { useForecastQuery } from "@/hooks/useCryptoData";
import { useWebSocketStream } from "@/hooks/useWebSocketStream";
import { useNotificationCenter } from "@/context/NotificationContext";
import { Sparkles, Zap, ShieldCheck, Activity, BarChart2, Volume2, VolumeX, Cpu, Layers } from "lucide-react";

export default function DashboardPage() {
  const [viewMode, setViewMode] = useState<"V16_TERMINAL" | "LEGACY_SCANNER">("V16_TERMINAL");
  const wsStatus = useWebSocketStream();
  const { data: forecast, isLoading } = useForecastQuery();
  const { soundEnabled, toggleSound, replaySound } = useNotificationCenter();
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [activeHorizon, setActiveHorizon] = useState<string>("DOMINANT");
  const [directionFilter, setDirectionFilter] = useState<"ALL" | "LONG" | "SHORT">("ALL");
  const [minReturnFilter, setMinReturnFilter] = useState<number>(0);
  const dominantSignals = forecast?.dominant_signals_per_coin || [];
  const topSignals = forecast?.top_round_signals || [];
  const signalsByHorizon = forecast?.signals_by_horizon || {};

  const horizonCategories = [
    { key: "DOMINANT", label: "💎 Top Setup Per Coin", tag: "DOMINANT" },
    { key: "ALL", label: "⚡ All Active Trades", tag: "ALL" },
    { key: "5M", label: "⚡ Micro (5M)", tag: "5M" },
    { key: "15M", label: "⚡ Scalp (15M)", tag: "15M" },
    { key: "1H", label: "⏳ Day Trade (1H)", tag: "1H" },
    { key: "4H", label: "⏳ Swing (4H)", tag: "4H" },
    { key: "12H", label: "🌊 Half-Day (12H)", tag: "12H" },
    { key: "24H", label: "🌊 Daily (1D)", tag: "24H" },
    { key: "7D", label: "📅 Weekly (7D)", tag: "7D" },
    { key: "15D", label: "📅 Bi-Weekly (15D)", tag: "15D" },
    { key: "1M", label: "🏛️ Monthly (1M)", tag: "1M" },
  ];

  // Helper to extract effective return % of a signal
  const getSignalReturnPct = (s: any): number => {
    const rawExp = s.expected_return_pct !== undefined ? Math.abs(Number(s.expected_return_pct)) : 0;
    const modelExp = s.exp_return !== undefined ? Math.abs(Number(s.exp_return) * 100) : 0;
    const entry = Number(s.entry_price || s.current_price || 0);
    const tp1 = Number(s.tp1_price || s.tp_price || 0);
    const tpGain = entry > 0 && tp1 > 0 ? (Math.abs(tp1 - entry) / entry) * 100 : 0;
    return Math.max(rawExp, modelExp, tpGain);
  };

  // Helper to match signal against active institutional horizon tabs (5M..1M)
  const matchesHorizonFilter = (s: any, tag: string): boolean => {
    const hStr = (s.horizon_tag || s.horizon || s.horizon_name || s.horizon_key || s.active_signal_horizon || s.dominant_timeframe || "").toUpperCase();
    if (tag === "5M") return hStr.includes("5M") || hStr.includes("5MIN");
    if (tag === "15M") return hStr.includes("15M") || hStr.includes("SCALP");
    if (tag === "1H") return (hStr.includes("1H") && !hStr.includes("15M")) || hStr.includes("DAY TRADE") || hStr.includes("INTRADAY") || hStr.includes("SWING (1H)");
    if (tag === "4H") return hStr.includes("4H") || hStr.includes("4HOUR");
    if (tag === "12H") return hStr.includes("12H") || hStr.includes("12HOUR");
    if (tag === "24H") return hStr.includes("24H") || hStr.includes("1D") || hStr.includes("SWING TRADE (1D)") || hStr.includes("MACRO");
    if (tag === "7D") return hStr.includes("7D") || hStr.includes("1W") || hStr.includes("WEEKLY");
    if (tag === "15D") return hStr.includes("15D") || hStr.includes("BI-WEEKLY");
    if (tag === "1M") return hStr.includes("1M") || hStr.includes("30D") || hStr.includes("MONTHLY");
    return false;
  };

  // Strictly filter only active, tradable signals (exclude won/lost/expired/NTZ/vetoed/delisted)
  const isSignalActive = (s: any): boolean => {
    if (!s) return false;
    const sym = String(s.symbol || "").toUpperCase();
    if (sym.includes("OLD") || sym.includes("DELISTED") || ["USDSOLD/USDT", "ERD/USDT", "VEN/USDT", "BCC/USDT", "NANO/USDT", "BTT/USDT"].includes(sym)) return false;
    if (s.is_trade_active === false) return false;
    if (s.is_ntz_active === true) return false;
    const sigStatus = String(s.signal_status || "").toUpperCase();
    if (sigStatus.includes("NO_TRADE_ZONE") || sigStatus.includes("WAITING") || sigStatus.includes("VETO")) return false;
    const dir = String(s.direction || s.dominant_direction || "").toUpperCase();
    if (dir === "NO_TRADE" || dir.includes("HOLD") || dir.includes("VETO")) return false;
    const st = String(s.status || "ACTIVE").toUpperCase();
    const outc = String(s.outcome_label || "").toUpperCase();
    if (st.includes("WON") || st.includes("LOST") || st.includes("EXPIRED") || st.includes("STOPPED")) return false;
    if (outc.includes("WON") || outc.includes("LOST") || outc.includes("EXPIRED") || outc.includes("STOPPED")) return false;
    return true;
  };

  // Helper to extract normalized horizon tag across all 9 horizons
  const getNormalizedHorizonTag = (s: any): string => {
    const hStr = (s.horizon_tag || s.horizon || s.horizon_name || s.active_signal_horizon || s.dominant_timeframe || "").toUpperCase();
    if (hStr.includes("5M")) return "5M";
    if (hStr.includes("15M") || hStr.includes("SCALP")) return "15M";
    if (hStr.includes("1H") || hStr.includes("DAY TRADE") || hStr.includes("INTRADAY")) return "1H";
    if (hStr.includes("4H")) return "4H";
    if (hStr.includes("12H")) return "12H";
    if (hStr.includes("24H") || hStr.includes("1D") || hStr.includes("MACRO")) return "24H";
    if (hStr.includes("7D") || hStr.includes("1W")) return "7D";
    if (hStr.includes("15D")) return "15D";
    if (hStr.includes("1M") || hStr.includes("30D")) return "1M";
    return hStr || "1H";
  };

  // Extract signals: in "ALL" mode, display all qualified timeframes per coin (e.g., 15M, 1H, 24H)
  const currentHorizonSignals = useMemo(() => {
    let list: any[] = [];
    if (activeHorizon === "DOMINANT") {
      const topBySym = new Map<string, any>();
      for (const ts of topSignals) {
        const sym = (ts.symbol || "").toUpperCase().replace("/", "").replace(":USDT", "");
        if (!topBySym.has(sym) || String(ts.quality_grade || "").includes("A+")) {
          topBySym.set(sym, ts);
        }
      }
      list = (dominantSignals.length > 0 ? dominantSignals : topSignals).map((s: any) => {
        const sym = (s.symbol || "").toUpperCase().replace("/", "").replace(":USDT", "");
        const activeMatch = topBySym.get(sym);
        if (activeMatch && (activeMatch.is_trade_active || activeMatch.trade_id)) {
          return {
            ...s,
            ...activeMatch,
            all_9_timeframe_predictions: s.all_9_timeframe_predictions || activeMatch.all_9_timeframe_predictions,
            horizons: s.horizons || activeMatch.horizons,
          };
        }
        return s;
      });
    } else if (activeHorizon === "ALL") {
      list = topSignals;
    } else if (signalsByHorizon[activeHorizon] && signalsByHorizon[activeHorizon].length > 0) {
      list = signalsByHorizon[activeHorizon];
    } else {
      list = topSignals.filter((s: any) => matchesHorizonFilter(s, activeHorizon));
    }

    // Filter to active-only signals
    list = list.filter(isSignalActive);

    // Group all active signals by symbol to detect multi-timeframe confluence & companions
    const signalsBySymbol: Record<string, any[]> = {};
    for (const s of list) {
      const sym = (s.symbol || "").toUpperCase().replace("/", "").replace(":USDT", "");
      if (!signalsBySymbol[sym]) signalsBySymbol[sym] = [];
      signalsBySymbol[sym].push(s);
    }

    const seenKeys = new Set<string>();
    const result: any[] = [];

    for (const s of list) {
      const sym = (s.symbol || "").toUpperCase().replace("/", "").replace(":USDT", "");
      const hTag = getNormalizedHorizonTag(s);
      
      // In DOMINANT mode, show 1 setup per coin. In ALL mode, show all qualified horizons per coin.
      const key = activeHorizon === "DOMINANT" ? sym : `${sym}_${hTag}`;
      
      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        // Enrich signal with companion horizons for this asset
        const coinSigs = signalsBySymbol[sym] || [];
        const companionHorizons = Array.from(new Set(coinSigs.map((cs) => getNormalizedHorizonTag(cs))));
        
        result.push({
          ...s,
          companion_horizons: companionHorizons,
          all_coin_signals: coinSigs,
          is_multi_timeframe: companionHorizons.length > 1,
        });
      }
    }
    return result;
  }, [dominantSignals, topSignals, signalsByHorizon, activeHorizon]);

  // Helper to count active setups per horizon category
  const getHorizonCount = (tag: string) => {
    let list: any[] = [];
    if (tag === "DOMINANT") {
      list = dominantSignals.length > 0 ? dominantSignals : topSignals;
    } else if (tag === "ALL") {
      list = topSignals;
    } else if (signalsByHorizon[tag] && signalsByHorizon[tag].length > 0) {
      list = signalsByHorizon[tag];
    } else {
      list = topSignals.filter((s: any) => matchesHorizonFilter(s, tag));
    }

    list = list.filter(isSignalActive);

    const seenKeys = new Set<string>();
    const dedupedList: any[] = [];
    for (const s of list) {
      const sym = (s.symbol || "").toUpperCase().replace("/", "").replace(":USDT", "");
      const hTag = getNormalizedHorizonTag(s);
      const key = tag === "DOMINANT" ? sym : `${sym}_${hTag}`;
      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        dedupedList.push(s);
      }
    }

    let filtered = dedupedList;
    if (directionFilter === "LONG") {
      filtered = filtered.filter((s: any) => s.direction === "LONG" || s.direction === "BULLISH");
    } else if (directionFilter === "SHORT") {
      filtered = filtered.filter((s: any) => s.direction === "SHORT" || s.direction === "BEARISH");
    }

    if (minReturnFilter > 0) {
      filtered = filtered.filter((s: any) => getSignalReturnPct(s) >= minReturnFilter);
    }

    return filtered.length;
  };

  const longCount = useMemo(() => {
    return currentHorizonSignals
      .filter((s: any) => s.direction === "LONG" || s.direction === "BULLISH")
      .filter((s: any) => minReturnFilter === 0 || getSignalReturnPct(s) >= minReturnFilter).length;
  }, [currentHorizonSignals, minReturnFilter]);

  const shortCount = useMemo(() => {
    return currentHorizonSignals
      .filter((s: any) => s.direction === "SHORT" || s.direction === "BEARISH")
      .filter((s: any) => minReturnFilter === 0 || getSignalReturnPct(s) >= minReturnFilter).length;
  }, [currentHorizonSignals, minReturnFilter]);

  // Filter signals according to active horizon, direction filter & minimum return filter
  const filteredTopSignals = useMemo(() => {
    let list = currentHorizonSignals;
    if (directionFilter === "LONG") {
      list = list.filter((s: any) => s.direction === "LONG" || s.direction === "BULLISH");
    } else if (directionFilter === "SHORT") {
      list = list.filter((s: any) => s.direction === "SHORT" || s.direction === "BEARISH");
    }
    if (minReturnFilter > 0) {
      list = list.filter((s: any) => getSignalReturnPct(s) >= minReturnFilter);
    }
    return list;
  }, [currentHorizonSignals, directionFilter, minReturnFilter]);

  return (
    <div className="space-y-6">
      {/* Terminal View Switcher Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3 bg-slate-900/60 backdrop-blur-xl p-3 sm:p-4 rounded-2xl border border-slate-800/60 shadow-lg">
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setViewMode("LEGACY_SCANNER")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl font-mono text-xs font-bold transition-all ${
              viewMode === "LEGACY_SCANNER"
                ? "bg-gradient-to-r from-cyan-600/30 to-indigo-600/30 text-cyan-300 border border-cyan-400/80 shadow-[0_0_15px_rgba(6,182,212,0.25)]"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent"
            }`}
          >
            <Layers className="w-3.5 h-3.5 text-cyan-400" />
            <span>110-COIN SCANNER MATRIX</span>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          </button>

          <button
            onClick={() => setViewMode("V16_TERMINAL")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl font-mono text-xs font-bold transition-all ${
              viewMode === "V16_TERMINAL"
                ? "bg-gradient-to-r from-cyan-600/30 via-indigo-600/30 to-emerald-600/30 text-white border border-cyan-400/80 shadow-[0_0_20px_rgba(6,182,212,0.3)]"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent"
            }`}
          >
            <Cpu className="w-3.5 h-3.5 text-cyan-400" />
            <span>QUANT EDGE V16 TERMINAL</span>
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          </button>
        </div>

        <div className="text-[11px] font-mono text-slate-400 hidden sm:flex items-center gap-2">
          <span>V16 Engine:</span>
          <span className="px-2 py-0.5 rounded-md bg-emerald-950/80 text-emerald-400 border border-emerald-500/30 font-bold flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> ACTIVE (VPS Verified)
          </span>
        </div>
      </div>

      {viewMode === "V16_TERMINAL" ? (
        <V16Dashboard />
      ) : (
        <div className="space-y-8">
          {/* ========================================================= */}
          {/* 1. HERO SECTION: Actionable Signals & Dedicated BTC Alpha */}
          {/* ========================================================= */}
          <section className="space-y-6">
            {/* Hero Banner Header */}
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between border-b border-slate-800/80 pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-400">
                    <Zap className="h-3.5 w-3.5 animate-pulse" />
                  </span>
                  <h1 className="text-xl sm:text-2xl font-black tracking-tight text-white">
                    Live Top 40 Quantitative Scanner Matrix
                  </h1>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  High-alpha confluence setups across 15M Scalp, 1H Day Trade, and 1D Swing horizons actively evaluated by fresh hybrid ML models.
                </p>
              </div>

          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="rounded-lg bg-dark-900/90 px-3 py-1.5 text-slate-300 border border-slate-800 flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${wsStatus.isConnected ? "bg-emerald-400 animate-pulse shadow-sm shadow-emerald-400" : "bg-amber-400"}`} />
              <span className="text-[11px] font-semibold text-slate-300">
                {wsStatus.isConnected ? "⚡ Live WebSocket Stream" : "REST Sync"}
              </span>
            </span>
            <button
              onClick={() => {
                toggleSound();
                if (!soundEnabled) replaySound("NEW_SIGNAL");
              }}
              title={soundEnabled ? "Audio Alerts Active (Click to Mute)" : "Audio Alerts Muted (Click to Enable)"}
              className={`rounded-lg px-3 py-1.5 border flex items-center gap-1.5 transition-colors ${
                soundEnabled
                  ? "bg-cyan-950/80 text-cyan-300 border-cyan-500/50 hover:bg-cyan-900/90"
                  : "bg-dark-900/90 text-slate-500 border-slate-800 hover:text-slate-400"
              }`}
            >
              {soundEnabled ? <Volume2 className="h-3.5 w-3.5 text-cyan-400 animate-pulse" /> : <VolumeX className="h-3.5 w-3.5" />}
              <span className="text-[11px] font-semibold">{soundEnabled ? "🔔 Audio Alerts ON" : "🔕 Audio Muted"}</span>
            </button>
            <span className="rounded-lg bg-dark-900/90 px-3 py-1.5 text-slate-300 border border-slate-800 flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-cyan-400" />
              <span>Active Signals: <strong className="text-cyan-300">{topSignals.length}</strong></span>
            </span>
          </div>
        </div>

        {/* 1.1 Actionable Top Institutional Signal Cards by Horizon & Direction */}
        <div>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 mb-3">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5 font-mono">
              <Sparkles className="h-4 w-4 text-cyan-400" /> Timeframe-Separated Actionable Signals ({filteredTopSignals.length} Active in {activeHorizon === "ALL" ? "All Timeframes" : (activeHorizon === "DOMINANT" ? "Dominant Setups" : activeHorizon)})
            </h2>
            <div className="flex items-center gap-2">
              {minReturnFilter > 0 && (
                <span className="rounded-lg bg-emerald-950 px-2.5 py-1 text-[11px] font-bold text-emerald-300 border border-emerald-700/60 flex items-center gap-1 font-mono">
                  🎯 Minimum {minReturnFilter}% Gain Target Active
                </span>
              )}
              <span className="text-[11px] text-emerald-400 font-mono font-semibold flex items-center gap-1">
                ✓ Min 0.20% Return Filter Active (Fees Protected)
              </span>
            </div>
          </div>

          {/* Controls Bar: Structured 2-Row Responsive Layout */}
          <div className="flex flex-col gap-3 mb-4 bg-dark-900/80 p-3 sm:p-4 rounded-2xl border border-slate-800/90 shadow-sm">
            {/* Row 1: Side & Gain in two responsive columns */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-center border-b border-slate-800/60 pb-3">
              {/* Column 1: Side Direction Filter */}
              <div className="flex items-center gap-1.5 sm:gap-2 bg-dark-950/90 p-1.5 rounded-xl border border-slate-800 w-full sm:w-auto">
                <span className="text-[10px] uppercase font-bold text-slate-400 px-2 font-mono shrink-0">
                  Side:
                </span>
                <div className="flex items-center gap-1 flex-1 flex-wrap sm:flex-nowrap">
                  <button
                    type="button"
                    onClick={() => setDirectionFilter("ALL")}
                    className={`flex-1 sm:flex-initial px-3 py-1.5 text-xs font-bold rounded-lg transition-all text-center ${
                      directionFilter === "ALL"
                        ? "bg-cyan-500/25 text-cyan-200 border border-cyan-500/40 shadow-sm"
                        : "text-slate-400 hover:text-white hover:bg-slate-800/50"
                    }`}
                  >
                    ⚡ All
                  </button>
                  <button
                    type="button"
                    onClick={() => setDirectionFilter("LONG")}
                    className={`flex-1 sm:flex-initial px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                      directionFilter === "LONG"
                        ? "bg-emerald-500/25 text-emerald-300 border border-emerald-500/50 shadow-sm shadow-emerald-500/20"
                        : "text-slate-400 hover:text-emerald-300 hover:bg-slate-800/50"
                    }`}
                  >
                    <span>🟢 Longs</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-700/50">
                      {longCount}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setDirectionFilter("SHORT")}
                    className={`flex-1 sm:flex-initial px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                      directionFilter === "SHORT"
                        ? "bg-rose-500/25 text-rose-300 border border-rose-500/50 shadow-sm shadow-rose-500/20"
                        : "text-slate-400 hover:text-rose-300 hover:bg-slate-800/50"
                    }`}
                  >
                    <span>🔴 Shorts</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-rose-950 text-rose-300 border border-rose-700/50">
                      {shortCount}
                    </span>
                  </button>
                </div>
              </div>

              {/* Column 2: Minimum Gain Target Filter */}
              <div className="flex items-center gap-1.5 sm:gap-2 bg-dark-950/90 p-1.5 rounded-xl border border-slate-800 w-full sm:w-auto md:justify-self-end">
                <span className="text-[10px] uppercase font-bold text-slate-400 px-2 font-mono shrink-0">
                  Gain:
                </span>
                <div className="flex items-center gap-1 flex-1 flex-wrap sm:flex-nowrap">
                  <button
                    type="button"
                    onClick={() => setMinReturnFilter(0)}
                    className={`flex-1 sm:flex-initial px-3 py-1.5 text-xs font-bold rounded-lg transition-all text-center ${
                      minReturnFilter === 0
                        ? "bg-cyan-500/25 text-cyan-200 border border-cyan-500/40"
                        : "text-slate-400 hover:text-white hover:bg-slate-800/50"
                    }`}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    onClick={() => setMinReturnFilter(3)}
                    className={`flex-1 sm:flex-initial px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1 ${
                      minReturnFilter === 3
                        ? "bg-emerald-500/25 text-emerald-300 border border-emerald-500/50 shadow-sm"
                        : "text-slate-400 hover:text-emerald-300 hover:bg-slate-800/50"
                    }`}
                  >
                    🎯 ≥ 3%
                  </button>
                  <button
                    type="button"
                    onClick={() => setMinReturnFilter(5)}
                    className={`flex-1 sm:flex-initial px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1 ${
                      minReturnFilter === 5
                        ? "bg-amber-500/25 text-amber-300 border border-amber-500/50 shadow-sm"
                        : "text-slate-400 hover:text-amber-300 hover:bg-slate-800/50"
                    }`}
                  >
                    💎 ≥ 5%
                  </button>
                </div>
              </div>
            </div>

            {/* Row 2: Horizon Category Tabs (Full width, responsive wrapping) */}
            <div className="flex items-center gap-2 overflow-x-auto touch-scroll no-scrollbar py-0.5 max-w-full flex-wrap sm:flex-nowrap">
              {horizonCategories.map((cat) => {
                const count = getHorizonCount(cat.tag);
                const isActive = activeHorizon === cat.tag;
                return (
                  <button
                    key={cat.key}
                    type="button"
                    onClick={() => setActiveHorizon(cat.tag)}
                    className={`flex items-center gap-2 whitespace-nowrap rounded-xl px-3 sm:px-4 py-2 text-xs font-bold transition-all shrink-0 ${
                      isActive
                        ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20"
                        : "bg-dark-950 text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-slate-800/80"
                    }`}
                  >
                    <span>{cat.label}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-mono ${
                        isActive
                          ? "bg-cyan-950 text-cyan-300 border border-cyan-700/50"
                          : count > 0
                          ? "bg-slate-800 text-slate-300 font-bold"
                          : "bg-slate-900 text-slate-600"
                      }`}
                    >
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {isLoading ? (
            <div className="py-12 text-center text-xs text-slate-500 font-mono glass-panel rounded-2xl">
              Loading actionable institutional setup cards across horizons...
            </div>
          ) : filteredTopSignals.length === 0 ? (
            <div className="glass-panel rounded-2xl p-6 sm:p-8 text-center text-slate-400 border border-slate-800">
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-dark-900 border border-slate-800 text-slate-500 mb-2">
                <Zap className="h-5 w-5" />
              </div>
              <div className="flex items-center justify-center gap-2 mb-2">
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-500/40">
                  POSTURE: {forecast?.market_trade_posture || "AWAITING MULTI-HORIZON ALIGNMENT"}
                </span>
                {forecast?.is_no_trade_zone_active && (
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-rose-950 text-rose-300 border border-rose-500/40">
                    🛑 NO TRADE ZONE ACTIVE
                  </span>
                )}
              </div>
              <h3 className="text-sm font-bold text-white">
                {activeHorizon === "ALL"
                  ? "No Grade A+ Setups Firing Right Now"
                  : `No High-Potential Setups in ${activeHorizon} This Round`}
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                {activeHorizon === "ALL"
                  ? "Market is in capital preservation / alignment mode. Live 9-Horizon Matrix below is actively tracking all assets across 5M to 30D."
                  : `This timeframe was skipped for safety because no asset met the strict ≥0.20% net gain and confluence criteria. Next evaluation on candle close.`}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {filteredTopSignals.map((sig: any, idx: number) => (
                <SignalCard key={sig.signal_id || `${sig.symbol}-${idx}`} signal={sig} rankIndex={idx} />
              ))}
            </div>
          )}
        </div>

        {/* 1.2 Institutional Trader Regime Playbook & Tactical Best Practices */}
        <TraderRegimePlaybookComponent />

        {/* 1.3 Dedicated Bitcoin (BTC) Intelligence & Command Station */}
        <BtcSignalSection />

        {/* 1.3 Executive Performance KPI Summary Ribbon */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5 font-mono">
              <ShieldCheck className="h-4 w-4 text-cyan-400" /> Executive Performance KPI Overview
            </h2>
            <span className="text-[11px] text-slate-500 font-mono">
              Auto-Syncing with MySQL Database
            </span>
          </div>
          <KpiMetrics />
        </div>
      </section>

      {/* ========================================================= */}
      {/* 2. COMPLETE PREDICTION SECTION: Top 100 Asset Universe     */}
      {/* ========================================================= */}
      <section>
        <AssetPredictionMatrix />
      </section>

      {/* ========================================================= */}
      {/* 3. PAPER TRADING BOT: Virtual Positions & Balance         */}
      {/* ========================================================= */}
      <section className="space-y-6">
        <PortfolioView />
        <QueuedTrades />
      </section>

      {/* ========================================================= */}
      {/* 4. AUDIT LEDGER & DAILY BREAKDOWN: 100% Verifiable Record */}
      {/* ========================================================= */}
      <section className="space-y-6">
        <DailySignalsView
          selectedDate={selectedDate}
          onSelectDate={(d) => setSelectedDate(d)}
        />

        <SignalsTable initialDate={selectedDate} key={selectedDate} />
      </section>
    </div>
    )}
  </div>
  );
}

