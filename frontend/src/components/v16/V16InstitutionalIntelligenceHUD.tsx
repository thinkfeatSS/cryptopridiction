"use client";

import React, { useState, useMemo } from "react";
import {
  Landmark,
  Calendar,
  Flame,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
  Layers,
  Crosshair,
  Activity,
  DollarSign,
  Globe,
  ChevronDown,
  ChevronUp,
  Clock,
  AlertTriangle,
  Zap,
  BarChart3,
  PieChart,
  Eye,
  RefreshCw,
} from "lucide-react";
import { MarketIntelligencePayload } from "@/types/v16";

interface Props {
  intelligence: MarketIntelligencePayload | null | undefined;
  isLoading: boolean;
  selectedSymbol?: string;
  onSymbolChange?: (symbol: string) => void;
  availableSymbols?: string[];
  onRefresh?: () => void;
}

export default function V16InstitutionalIntelligenceHUD({
  intelligence,
  isLoading,
  selectedSymbol = "BTC/USDT",
  onSymbolChange,
  availableSymbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "SUI/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "NEAR/USDT"],
  onRefresh,
}: Props) {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<"macro" | "dominance" | "sentiment" | "etf" | "whales" | "liquidations">("macro");

  // Dynamic coin universe for quick selection
  const coinList = useMemo(() => {
    const list = Array.from(new Set([
      "BTC/USDT",
      "ETH/USDT",
      "SOL/USDT",
      "SUI/USDT",
      "DOGE/USDT",
      "AVAX/USDT",
      selectedSymbol,
      ...(availableSymbols || [])
    ])).filter(Boolean);
    return list.slice(0, 10);
  }, [selectedSymbol, availableSymbols]);

  if (isLoading && !intelligence) {
    return (
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-4 backdrop-blur-md animate-pulse">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cyan-900/40" />
            <div className="space-y-1">
              <div className="w-48 h-4 rounded bg-slate-800" />
              <div className="w-32 h-3 rounded bg-slate-800/60" />
            </div>
          </div>
          <div className="w-24 h-6 rounded bg-slate-800" />
        </div>
      </div>
    );
  }

  if (!intelligence) {
    return null;
  }

  const {
    macro_calendar: macro,
    dominance_matrix: dominance,
    dual_sentiment: sentiment,
    etf_flows: etf,
    exchange_flows: flows,
    hyperliquid_whale_radar: whales,
    liquidation_heatmap: liqs,
    synthesized_at_utc: synthTime,
  } = intelligence;

  // Formatting helpers
  const formatCountdown = (minutes: number | null) => {
    if (minutes === null || minutes === undefined) return "No events scheduled";
    if (minutes < 0) return `${Math.abs(Math.round(minutes))}m ago`;
    const hours = Math.floor(minutes / 60);
    const mins = Math.floor(minutes % 60);
    if (hours > 24) {
      const days = Math.floor(hours / 24);
      return `${days}d ${hours % 24}h`;
    }
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  };

  const formatUsdMillions = (val: number | undefined) => {
    if (val === undefined || isNaN(val)) return "$0.0M";
    const sign = val > 0 ? "+" : "";
    return `${sign}$${val.toFixed(1)}M`;
  };

  // Status Colors
  const isBlackout = macro?.is_volatility_pause_active;
  const isFedSilence = macro?.fed_blackout_active;
  const cryptoScore = sentiment?.crypto_fear_and_greed?.score ?? 50;

  return (
    <div className="rounded-2xl border border-slate-800/90 bg-[#0c1017]/95 shadow-xl backdrop-blur-md overflow-hidden relative transition-all duration-300">
      {/* Top Ambient Glow Bar */}
      <div
        className={`h-1 w-full transition-all duration-500 ${
          isBlackout
            ? "bg-rose-500 animate-pulse shadow-[0_0_15px_rgba(244,63,94,0.6)]"
            : "bg-gradient-to-r from-cyan-500 via-indigo-500 to-emerald-500"
        }`}
      />

      {/* Primary Intelligence Tape / Header Bar */}
      <div className="p-3.5 sm:p-4 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/60 bg-slate-900/40">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-gradient-to-br from-cyan-950 to-indigo-950 border border-cyan-500/30 text-cyan-400 shadow-sm">
            <Landmark className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-black tracking-tight text-white font-mono uppercase">
                Institutional Macro &amp; Whale Radar HUD
              </h3>
              <span className="text-[10px] px-2 py-0.5 rounded-full font-mono font-bold bg-cyan-950/80 border border-cyan-500/30 text-cyan-300">
                V16 TAPE
              </span>
              {isBlackout && (
                <span className="text-[10px] px-2 py-0.5 rounded-full font-mono font-black bg-rose-950 border border-rose-500 text-rose-300 animate-pulse flex items-center gap-1">
                  <ShieldAlert className="w-3 h-3 text-rose-400" />
                  MACRO BLACKOUT ACTIVE
                </span>
              )}
              {isFedSilence && !isBlackout && (
                <span className="text-[10px] px-2 py-0.5 rounded-full font-mono font-bold bg-amber-950/70 border border-amber-500/40 text-amber-300 flex items-center gap-1">
                  <Clock className="w-3 h-3 text-amber-400" />
                  FED SILENCE PERIOD
                </span>
              )}
            </div>
            <p className="text-[11px] text-slate-400 font-mono mt-0.5">
              Fed/FOMC Calendar • Spot ETF Velocity • Hyperliquid Whale Depth • Dominance Matrix
            </p>
          </div>
        </div>

        {/* Quick KPI Badges on the right */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Next Macro Event Quick Pill */}
          <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs font-mono">
            <Calendar className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-slate-400">Next:</span>
            <span className="text-slate-200 font-bold truncate max-w-[140px]">
              {macro?.event_name ? macro.event_name.split("&")[0] : "None"}
            </span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
              (macro?.minutes_until_event ?? 9999) < 60
                ? "bg-rose-950/80 text-rose-400 border border-rose-800/60"
                : "bg-slate-800/80 text-cyan-300"
            }`}>
              {formatCountdown(macro?.minutes_until_event ?? null)}
            </span>
          </div>

          {/* ETF Net Inflow Pill */}
          <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs font-mono">
            <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-slate-400">ETF 5D:</span>
            <span className={`font-bold ${(etf?.bitcoin_spot_etf?.cumulative_5d_flow_usd_m ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {formatUsdMillions(etf?.bitcoin_spot_etf?.cumulative_5d_flow_usd_m)}
            </span>
          </div>

          {/* Fear & Greed Mini Pill */}
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs font-mono">
            <Flame className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-slate-400">F&amp;G:</span>
            <span className={`font-bold ${cryptoScore >= 60 ? "text-emerald-400" : cryptoScore <= 35 ? "text-rose-400" : "text-amber-400"}`}>
              {cryptoScore}
            </span>
          </div>

          {/* Refresh Action */}
          {onRefresh && (
            <button
              onClick={onRefresh}
              className="p-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-400 hover:text-cyan-400 transition-colors"
              title="Refresh Institutional Intelligence"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}

          {/* Accordion Toggle */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-slate-700 text-xs font-mono text-slate-300 transition-colors"
          >
            <span>{isExpanded ? "Hide" : "Details"}</span>
            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Critical Volatility Blackout Alert Banner if Active */}
      {isBlackout && (
        <div className="px-4 py-2.5 bg-rose-950/60 border-b border-rose-500/40 flex items-center justify-between text-xs font-mono text-rose-200">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 animate-bounce" />
            <span className="font-bold uppercase">Trading Pause Active:</span>
            <span>{macro?.pause_reason || "US Macro Volatility Release Blackout window in effect."}</span>
          </div>
          <span className="text-[11px] text-rose-400">Gated by V16 Capital Preservation Rule</span>
        </div>
      )}

      {/* Expandable Deep Analytics Drawer */}
      {isExpanded && (
        <div className="p-3.5 sm:p-5 space-y-4">
          {/* Navigation Tabs */}
          <div className="flex items-center gap-1.5 border-b border-slate-800/80 pb-2 overflow-x-auto text-xs font-mono">
            <button
              onClick={() => setActiveTab("macro")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
                activeTab === "macro"
                  ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Calendar className="w-3.5 h-3.5" />
              <span>Fed / Macro Calendar</span>
            </button>

            <button
              onClick={() => setActiveTab("whales")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
                activeTab === "whales"
                  ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Eye className="w-3.5 h-3.5 text-indigo-400" />
              <span>Hyperliquid Whale Radar</span>
            </button>

            <button
              onClick={() => setActiveTab("etf")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
                activeTab === "etf"
                  ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
              <span>Spot ETF Inflows</span>
            </button>

            <button
              onClick={() => setActiveTab("dominance")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
                activeTab === "dominance"
                  ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <PieChart className="w-3.5 h-3.5 text-amber-400" />
              <span>Dominance &amp; Rotation</span>
            </button>

            <button
              onClick={() => setActiveTab("sentiment")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
                activeTab === "sentiment"
                  ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Flame className="w-3.5 h-3.5 text-orange-400" />
              <span>Dual Fear &amp; Greed</span>
            </button>

            <button
              onClick={() => setActiveTab("liquidations")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
                activeTab === "liquidations"
                  ? "bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Crosshair className="w-3.5 h-3.5 text-rose-400" />
              <span>Liquidation Heatmap</span>
            </button>
          </div>

          {/* TAB 1: FED / MACRO CALENDAR */}
          {activeTab === "macro" && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-1 rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono text-slate-400 uppercase tracking-wide">Next Key Event</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold ${
                    macro?.impact === "CRITICAL"
                      ? "bg-rose-950 border border-rose-600 text-rose-300"
                      : "bg-indigo-950 border border-indigo-600 text-indigo-300"
                  }`}>
                    {macro?.impact || "HIGH"} IMPACT
                  </span>
                </div>

                <div className="text-base font-bold text-white font-mono leading-snug">
                  {macro?.event_name || "No imminent releases"}
                </div>

                <div className="flex items-center gap-2 text-xs font-mono text-slate-300">
                  <Clock className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Time until:</span>
                  <span className="font-bold text-cyan-300">
                    {formatCountdown(macro?.minutes_until_event ?? null)}
                  </span>
                </div>

                <div className="text-xs font-mono text-slate-400 pt-2 border-t border-slate-900">
                  <span>Scheduled: {macro?.event_time_utc || "TBD"}</span>
                </div>

                <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 text-[11px] font-mono text-slate-300 space-y-1">
                  <div className="font-bold text-cyan-400">Fed Framework Protocol:</div>
                  <p className="text-slate-400">
                    Pre-release volatility blackout triggers 30m prior. Signals during high-impact releases require &ge; 2.2R hurdle.
                  </p>
                </div>
              </div>

              {/* Upcoming Macro Schedule Table */}
              <div className="lg:col-span-2 rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono text-slate-400 uppercase tracking-wide">
                    Upcoming US Federal Reserve &amp; Economic Calendar
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">Auto-synchronized</span>
                </div>

                <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
                  {(macro?.upcoming_events || []).map((ev, idx) => (
                    <div
                      key={idx}
                      className="p-2.5 rounded-lg bg-slate-900/50 border border-slate-800/60 hover:border-slate-700/80 transition-colors flex items-center justify-between gap-3 text-xs font-mono"
                    >
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className={`w-1.5 h-1.5 rounded-full ${
                            ev.impact === "CRITICAL" ? "bg-rose-500" : "bg-cyan-500"
                          }`} />
                          <span className="font-bold text-slate-200">{ev.name}</span>
                        </div>
                        <p className="text-[11px] text-slate-400 truncate max-w-[420px]">{ev.description}</p>
                      </div>

                      <div className="text-right shrink-0">
                        <div className="text-cyan-300 font-bold">{formatCountdown(ev.minutes_until)}</div>
                        <div className="text-[10px] text-slate-500">{ev.time_utc.split(" ")[0]}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: HYPERLIQUID WHALE RADAR */}
          {activeTab === "whales" && (
            <div className="space-y-4">
              {/* Asset Selector Row */}
              <div className="flex items-center justify-between flex-wrap gap-2 p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/80">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-[11px] font-mono text-slate-400 font-bold uppercase tracking-wide mr-1">
                    Select Coin:
                  </span>
                  {coinList.map((coin: string) => {
                    const clean = coin.split("/")[0].split(":")[0].toUpperCase();
                    const isSelected = (whales?.symbol || selectedSymbol || "BTC").toUpperCase().includes(clean);
                    return (
                      <button
                        key={coin}
                        onClick={() => onSymbolChange?.(coin.includes("/") ? coin : `${coin}/USDT`)}
                        className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all ${
                          isSelected
                            ? "bg-indigo-600 text-white shadow-md shadow-indigo-900/30 border border-indigo-400"
                            : "bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-800"
                        }`}
                      >
                        {clean}
                      </button>
                    );
                  })}
                </div>
                <div className="text-[11px] font-mono text-slate-400 flex items-center gap-2">
                  <span>Active Book:</span>
                  <span className="text-cyan-300 font-bold bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                    {whales?.symbol || selectedSymbol}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-slate-400 uppercase tracking-wide">
                      {whales?.symbol || "BTC"} Whale Bias
                    </span>
                    <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold ${
                      whales?.whale_bias === "BULLISH_WHALE_BID_ABSORPTION"
                        ? "bg-emerald-950 border border-emerald-600 text-emerald-300"
                        : whales?.whale_bias === "BEARISH_WHALE_ASK_RESISTANCE"
                        ? "bg-rose-950 border border-rose-600 text-rose-300"
                        : "bg-slate-800 text-slate-300"
                    }`}>
                      {whales?.whale_bias || "BALANCED"}
                    </span>
                  </div>

                  <div className="space-y-2 pt-1 font-mono text-xs">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Mark Price:</span>
                      <span className="text-white font-bold">${whales?.mark_price ? whales.mark_price.toLocaleString() : "---"}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">8h Funding Rate:</span>
                      <span className={`font-bold ${(whales?.funding_rate_8h_pct ?? 0) >= 0 ? "text-cyan-300" : "text-amber-400"}`}>
                        {whales?.funding_rate_8h_pct !== undefined ? `${whales.funding_rate_8h_pct > 0 ? "+" : ""}${whales.funding_rate_8h_pct.toFixed(4)}%` : "0.0100%"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Open Interest:</span>
                      <span className="text-slate-200 font-bold">
                        {whales?.open_interest_usd ? `$${(whales.open_interest_usd / 1e6).toFixed(1)}M` : "---"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Confluence Boost:</span>
                      <span className={`font-bold ${(whales?.confluence_boost_pct ?? 0) > 0 ? "text-emerald-400" : (whales?.confluence_boost_pct ?? 0) < 0 ? "text-rose-400" : "text-slate-400"}`}>
                        {(whales?.confluence_boost_pct ?? 0) > 0 ? `+${whales?.confluence_boost_pct}%` : `${whales?.confluence_boost_pct ?? 0}%`}
                      </span>
                    </div>
                  </div>

                  <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 text-[11px] font-mono text-slate-300 space-y-1">
                    <div className="font-bold text-indigo-400">Hyperliquid L2 Book Scan:</div>
                    <p className="text-slate-400">
                      Tiered limit order wall filters (Tier 1: &ge;$200K, Tier 2: &ge;$60K, Altcoins: &ge;$15K). Smart money skew dynamically impacts signal conviction.
                    </p>
                  </div>
                </div>

                {/* Whale Bid Walls vs Whale Ask Walls */}
                <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                  {/* Whale Bids */}
                  <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-3.5 space-y-2">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                        <TrendingUp className="w-3.5 h-3.5" /> Whale Bids (Resting Walls)
                      </span>
                      <span className="text-slate-400">
                        Total: ${((whales?.total_whale_bid_notional_usd ?? 0) / 1e6).toFixed(2)}M
                      </span>
                    </div>
                    <div className="space-y-1.5 font-mono text-xs max-h-[160px] overflow-y-auto">
                      {(whales?.whale_bid_walls || []).length > 0 ? (
                        whales?.whale_bid_walls.map((b, i) => (
                          <div key={i} className="flex justify-between items-center p-1.5 rounded bg-emerald-950/20 border border-emerald-900/30">
                            <span className="text-emerald-300 font-bold">${b.price.toLocaleString()}</span>
                            <span className="text-slate-300">{b.size.toFixed(2)} coins</span>
                            <span className="text-emerald-400 font-bold">${(b.notional_usd / 1e3).toFixed(0)}K</span>
                          </div>
                        ))
                      ) : (
                        <div className="text-slate-500 text-center py-4 text-[11px]">No qualifying resting whale bids</div>
                      )}
                    </div>
                  </div>

                  {/* Whale Asks */}
                  <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-3.5 space-y-2">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-rose-400 font-bold flex items-center gap-1.5">
                        <TrendingDown className="w-3.5 h-3.5" /> Whale Asks (Resting Walls)
                      </span>
                      <span className="text-slate-400">
                        Total: ${((whales?.total_whale_ask_notional_usd ?? 0) / 1e6).toFixed(2)}M
                      </span>
                    </div>
                    <div className="space-y-1.5 font-mono text-xs max-h-[160px] overflow-y-auto">
                      {(whales?.whale_ask_walls || []).length > 0 ? (
                        whales?.whale_ask_walls.map((a, i) => (
                          <div key={i} className="flex justify-between items-center p-1.5 rounded bg-rose-950/20 border border-rose-900/30">
                            <span className="text-rose-300 font-bold">${a.price.toLocaleString()}</span>
                            <span className="text-slate-300">{a.size.toFixed(2)} coins</span>
                            <span className="text-rose-400 font-bold">${(a.notional_usd / 1e3).toFixed(0)}K</span>
                          </div>
                        ))
                      ) : (
                        <div className="text-slate-500 text-center py-4 text-[11px]">No qualifying resting whale asks</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: SPOT ETF INFLOWS & CEX RESERVES */}
          {activeTab === "etf" && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3 font-mono text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 uppercase tracking-wide">Institutional ETF Stance</span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 border border-emerald-600 text-emerald-300">
                    {etf?.institutional_bias?.replace("INSTITUTIONAL_", "") || "ACCUMULATION"}
                  </span>
                </div>

                <div className="text-slate-300 text-[11px] leading-relaxed">
                  {etf?.institutional_description || "Institutional Spot ETF inflows provide macro liquidity tailwind."}
                </div>

                <div className="pt-2 border-t border-slate-900 space-y-1.5">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Veto Macro Shorts:</span>
                    <span className={`font-bold ${etf?.veto_macro_btc_shorts ? "text-rose-400" : "text-slate-300"}`}>
                      {etf?.veto_macro_btc_shorts ? "YES (ACTIVE)" : "NO"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">CEX Flow Regime:</span>
                    <span className="text-cyan-300 font-bold">{flows?.flow_regime?.replace("CEX_", "") || "BALANCED"}</span>
                  </div>
                </div>
              </div>

              {/* Bitcoin Spot ETF Card */}
              <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3 font-mono text-xs">
                <div className="flex items-center justify-between border-b border-slate-900 pb-2">
                  <span className="font-bold text-white flex items-center gap-1.5">
                    <DollarSign className="w-4 h-4 text-amber-400" /> Bitcoin Spot ETFs
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                    (etf?.bitcoin_spot_etf?.daily_net_flow_usd_m ?? 0) >= 0 ? "bg-emerald-950 text-emerald-400" : "bg-rose-950 text-rose-400"
                  }`}>
                    {etf?.bitcoin_spot_etf?.flow_direction || "NET_INFLOW"}
                  </span>
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Daily Net Flow:</span>
                    <span className={`font-bold ${(etf?.bitcoin_spot_etf?.daily_net_flow_usd_m ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {formatUsdMillions(etf?.bitcoin_spot_etf?.daily_net_flow_usd_m)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">5-Day Cumulative Velocity:</span>
                    <span className={`font-bold ${(etf?.bitcoin_spot_etf?.cumulative_5d_flow_usd_m ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {formatUsdMillions(etf?.bitcoin_spot_etf?.cumulative_5d_flow_usd_m)}
                    </span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-400">Top Inflow Fund:</span>
                    <span className="text-slate-300">{etf?.bitcoin_spot_etf?.top_inflow_fund?.split("(")[1]?.replace(")", "") || "IBIT"} ({formatUsdMillions(etf?.bitcoin_spot_etf?.top_inflow_amount_usd_m)})</span>
                  </div>
                </div>
              </div>

              {/* Ethereum Spot ETF & Stablecoin Dry Powder */}
              <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3 font-mono text-xs">
                <div className="flex items-center justify-between border-b border-slate-900 pb-2">
                  <span className="font-bold text-white flex items-center gap-1.5">
                    <Activity className="w-4 h-4 text-indigo-400" /> Ethereum ETFs &amp; CEX Flows
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                    (etf?.ethereum_spot_etf?.daily_net_flow_usd_m ?? 0) >= 0 ? "bg-emerald-950 text-emerald-400" : "bg-rose-950 text-rose-400"
                  }`}>
                    {formatUsdMillions(etf?.ethereum_spot_etf?.daily_net_flow_usd_m)}
                  </span>
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-slate-400">ETH 5D Velocity:</span>
                    <span className={`font-bold ${(etf?.ethereum_spot_etf?.cumulative_5d_flow_usd_m ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {formatUsdMillions(etf?.ethereum_spot_etf?.cumulative_5d_flow_usd_m)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Stablecoin Fresh Powder:</span>
                    <span className="text-emerald-400 font-bold">
                      {formatUsdMillions(flows?.stablecoin_exchange_flow?.net_dry_powder_inflow_usd_m)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">CEX BTC Net Outflow:</span>
                    <span className="text-cyan-300 font-bold">
                      {formatUsdMillions(flows?.btc_exchange_flow?.net_flow_24h_usd_m)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: DOMINANCE & ROTATION */}
          {activeTab === "dominance" && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3 font-mono text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 uppercase tracking-wide">Capital Rotation Regime</span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-950 border border-indigo-600 text-indigo-300">
                    {dominance?.capital_rotation_regime || "BALANCED"}
                  </span>
                </div>

                <p className="text-slate-300 text-[11px] leading-relaxed">
                  {dominance?.rotation_description || "Equilibrium rotation across Bitcoin and Altcoin ecosystems."}
                </p>

                <div className="pt-2 border-t border-slate-900 space-y-1.5">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Alt Sizing Multiplier:</span>
                    <span className="text-cyan-300 font-bold">{dominance?.alt_sizing_multiplier?.toFixed(2)}x</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">BTC Sizing Multiplier:</span>
                    <span className="text-cyan-300 font-bold">{dominance?.btc_sizing_multiplier?.toFixed(2)}x</span>
                  </div>
                </div>
              </div>

              {/* Dominance Breakdown Progress Bars */}
              <div className="lg:col-span-2 rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3 font-mono text-xs">
                <span className="text-slate-400 uppercase tracking-wide">Market Cap Dominance Weights</span>

                <div className="space-y-3 pt-1">
                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span>Bitcoin Dominance (BTC.D)</span>
                      <span className="font-bold text-amber-400">{dominance?.btc_dominance_pct?.toFixed(1)}%</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-slate-900 overflow-hidden">
                      <div className="h-full bg-amber-400 rounded-full" style={{ width: `${dominance?.btc_dominance_pct || 57}%` }} />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span>Ethereum Dominance (ETH.D)</span>
                      <span className="font-bold text-indigo-400">{dominance?.eth_dominance_pct?.toFixed(1)}%</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-slate-900 overflow-hidden">
                      <div className="h-full bg-indigo-400 rounded-full" style={{ width: `${dominance?.eth_dominance_pct || 14}%` }} />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span>Stablecoin Dominance (USDT + USDC)</span>
                      <span className="font-bold text-emerald-400">{dominance?.stablecoin_dominance_pct?.toFixed(1)}%</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-slate-900 overflow-hidden">
                      <div className="h-full bg-emerald-400 rounded-full" style={{ width: `${(dominance?.stablecoin_dominance_pct || 7) * 3}%` }} />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-slate-300 mb-1">
                      <span>Altcoins &amp; Others (OTHERS.D)</span>
                      <span className="font-bold text-cyan-400">{dominance?.others_dominance_pct?.toFixed(1)}%</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-slate-900 overflow-hidden">
                      <div className="h-full bg-cyan-400 rounded-full" style={{ width: `${dominance?.others_dominance_pct || 22}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 5: DUAL FEAR & GREED */}
          {activeTab === "sentiment" && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 font-mono text-xs">
              {/* Crypto Fear & Greed */}
              <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 uppercase tracking-wide">Crypto Sentiment</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                    cryptoScore >= 60 ? "bg-emerald-950 text-emerald-300" : cryptoScore <= 40 ? "bg-rose-950 text-rose-300" : "bg-amber-950 text-amber-300"
                  }`}>
                    {sentiment?.crypto_fear_and_greed?.classification || "Neutral"}
                  </span>
                </div>

                <div className="flex items-center justify-center py-2">
                  <div className="text-4xl font-black text-white">
                    {cryptoScore}
                    <span className="text-xs text-slate-500 font-normal ml-1">/100</span>
                  </div>
                </div>

                <div className="text-[11px] text-slate-400 space-y-1">
                  <div className="flex justify-between">
                    <span>Directive:</span>
                    <span className="text-slate-200">{sentiment?.crypto_fear_and_greed?.directive || "Standard"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>7D Trend:</span>
                    <span className="text-cyan-300">{sentiment?.crypto_fear_and_greed?.trend_7d || "STABLE"}</span>
                  </div>
                </div>
              </div>

              {/* TradFi Fear & Greed */}
              <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 uppercase tracking-wide">TradFi Equities / VIX</span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300">
                    {sentiment?.traditional_fear_and_greed?.classification || "Neutral"}
                  </span>
                </div>

                <div className="flex items-center justify-center py-2">
                  <div className="text-4xl font-black text-white">
                    {sentiment?.traditional_fear_and_greed?.score ?? 55}
                    <span className="text-xs text-slate-500 font-normal ml-1">/100</span>
                  </div>
                </div>

                <p className="text-[11px] text-slate-400">
                  {sentiment?.traditional_fear_and_greed?.proxy_benchmark || "US Equities S&P 500 & CBOE VIX Volatility Index"}
                </p>
              </div>

              {/* Divergence & Contrarian Setup */}
              <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                <span className="text-slate-400 uppercase tracking-wide">Cross-Market Divergence</span>

                <div className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 space-y-1.5">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Status:</span>
                    <span className="text-cyan-300 font-bold">
                      {sentiment?.sentiment_divergence?.status || "CONVERGENT"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Delta (&Delta;):</span>
                    <span className="text-white font-bold">
                      {sentiment?.sentiment_divergence?.delta !== undefined ? `${sentiment.sentiment_divergence.delta > 0 ? "+" : ""}${sentiment.sentiment_divergence.delta}` : "0.0"}
                    </span>
                  </div>
                </div>

                <p className="text-[11px] text-slate-300 leading-relaxed">
                  {sentiment?.sentiment_divergence?.description || "Market sentiment is balanced across crypto and equities."}
                </p>
              </div>
            </div>
          )}

          {/* TAB 6: LIQUIDATION HEATMAP */}
          {activeTab === "liquidations" && (
            <div className="space-y-4">
              {/* Asset Selector Row */}
              <div className="flex items-center justify-between flex-wrap gap-2 p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/80">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-[11px] font-mono text-slate-400 font-bold uppercase tracking-wide mr-1">
                    Select Coin:
                  </span>
                  {coinList.map((coin: string) => {
                    const clean = coin.split("/")[0].split(":")[0].toUpperCase();
                    const isSelected = (liqs?.symbol || selectedSymbol || "BTC").toUpperCase().includes(clean);
                    return (
                      <button
                        key={coin}
                        onClick={() => onSymbolChange?.(coin.includes("/") ? coin : `${coin}/USDT`)}
                        className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all ${
                          isSelected
                            ? "bg-rose-600 text-white shadow-md shadow-rose-900/30 border border-rose-400"
                            : "bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-800"
                        }`}
                      >
                        {clean}
                      </button>
                    );
                  })}
                </div>
                <div className="text-[11px] font-mono text-slate-400 flex items-center gap-2">
                  <span>Current Asset &amp; Price:</span>
                  <span className="text-emerald-400 font-bold bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                    {liqs?.symbol || selectedSymbol}: ${liqs?.current_price ? liqs.current_price.toLocaleString() : "---"}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 font-mono text-xs">
                {/* Short Liquidation Pools (Upside Magnets) */}
                <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                      <TrendingUp className="w-3.5 h-3.5" /> Short Liquidation Magnets (Upside TP Targets)
                    </span>
                    <span className="text-[10px] text-slate-400">Hunting Stop Cascades</span>
                  </div>

                  <div className="space-y-2">
                    {(liqs?.short_liquidation_pools || []).map((pool, i) => (
                      <div key={i} className="flex justify-between items-center p-2 rounded bg-emerald-950/20 border border-emerald-900/30">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-950 border border-emerald-700 text-emerald-300">
                          {pool.leverage}
                        </span>
                        <span className="text-emerald-300 font-bold">${pool.price.toLocaleString()}</span>
                        <span className="text-slate-400">+{pool.distance_pct}% away</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          pool.density === "CRITICAL_MAGNET" ? "bg-rose-950 text-rose-300 border border-rose-800 font-bold" : "text-slate-400"
                        }`}>
                          {pool.density}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div className="p-2 rounded bg-slate-900/80 border border-slate-800 text-[11px] text-slate-300">
                    <span className="text-cyan-400 font-bold">Optimal Long TP Anchor: </span>
                    <span>${liqs?.target_magnet_long ? liqs.target_magnet_long.toLocaleString() : "---"}</span>
                  </div>
                </div>

                {/* Long Liquidation Pools (Downside Magnets) */}
                <div className="rounded-xl bg-slate-950/60 border border-slate-800/80 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-rose-400 font-bold flex items-center gap-1.5">
                      <TrendingDown className="w-3.5 h-3.5" /> Long Liquidation Magnets (Downside TP Targets)
                    </span>
                    <span className="text-[10px] text-slate-400">Hunting Stop Cascades</span>
                  </div>

                  <div className="space-y-2">
                    {(liqs?.long_liquidation_pools || []).map((pool, i) => (
                      <div key={i} className="flex justify-between items-center p-2 rounded bg-rose-950/20 border border-rose-900/30">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-950 border border-rose-700 text-rose-300">
                          {pool.leverage}
                        </span>
                        <span className="text-rose-300 font-bold">${pool.price.toLocaleString()}</span>
                        <span className="text-slate-400">{pool.distance_pct}% away</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          pool.density === "CRITICAL_MAGNET" ? "bg-rose-950 text-rose-300 border border-rose-800 font-bold" : "text-slate-400"
                        }`}>
                          {pool.density}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div className="p-2 rounded bg-slate-900/80 border border-slate-800 text-[11px] text-slate-300">
                    <span className="text-cyan-400 font-bold">Optimal Short TP Anchor: </span>
                    <span>${liqs?.target_magnet_short ? liqs.target_magnet_short.toLocaleString() : "---"}</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Timestamp and Audit Footer */}
          <div className="flex justify-between items-center text-[10px] font-mono text-slate-500 pt-2 border-t border-slate-800/60">
            <span>Unified Quant Intelligence Hub • Ingests FOMC, CPI, NFP, Spot ETFs, Hyperliquid L2 &amp; Liquidations</span>
            <span>Synthesized: {synthTime || "Live"}</span>
          </div>
        </div>
      )}
    </div>
  );
}
