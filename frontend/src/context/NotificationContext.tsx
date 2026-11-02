"use client";

import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { SignalNotification, NotificationType } from "@/types/notifications";
import { useForecastQuery, usePortfolioQuery } from "@/hooks/useCryptoData";
import { formatServerPredictionTime } from "@/hooks/useRelativeTime";
import {
  playSignalChime,
  playParabolicBreakoutAlert,
  playExhaustionSellAlert,
  playTpHitChime,
  playSlHitChime,
  playBreakEvenChime,
  playExpiredChime,
} from "@/lib/audioAlert";

interface NotificationContextValue {
  notifications: SignalNotification[];
  unreadCount: number;
  activeToast: SignalNotification | null;
  dismissActiveToast: () => void;
  isDrawerOpen: boolean;
  setIsDrawerOpen: (open: boolean) => void;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  clearNotifications: () => void;
  soundEnabled: boolean;
  toggleSound: () => void;
  replaySound: (type: NotificationType) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<SignalNotification[]>([]);
  const [activeToast, setActiveToast] = useState<SignalNotification | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);
  const [soundEnabled, setSoundEnabled] = useState<boolean>(true);

  const { data: forecastData } = useForecastQuery();
  const { data: portfolioData } = usePortfolioQuery();

  const prevSignalStatusMap = useRef<Map<string, string>>(new Map());
  const seenSignalIds = useRef<Set<string>>(new Set());
  const seenClosedTradeIds = useRef<Set<string>>(new Set());
  const isInitialLoad = useRef<boolean>(true);
  const isInitialPortfolioLoad = useRef<boolean>(true);

  // Load sound preferences from localStorage
  useEffect(() => {
    try {
      const storedSound = localStorage.getItem("quantedge_sound_enabled");
      if (storedSound !== null) {
        setSoundEnabled(storedSound === "true");
      }
    } catch (e) {
      console.warn("Could not read sound preferences:", e);
    }
  }, []);

  const toggleSound = () => {
    setSoundEnabled((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("quantedge_sound_enabled", String(next));
      } catch (e) {
        console.warn("Could not save sound preferences:", e);
      }
      return next;
    });
  };

  const replaySound = (type: NotificationType) => {
    if (!soundEnabled) return;
    switch (type) {
      case "HYPE_SURGE":
        playParabolicBreakoutAlert(0.35);
        break;
      case "BLOWOFF_TOP":
        playExhaustionSellAlert(0.38);
        break;
      case "TP_HIT":
        playTpHitChime(0.38);
        break;
      case "SL_HIT":
        playSlHitChime(0.32);
        break;
      case "BREAKEVEN_PROTECTED":
        playBreakEvenChime(0.30);
        break;
      case "EXPIRED":
        playExpiredChime(0.25);
        break;
      case "NEW_SIGNAL":
      default:
        playSignalChime(0.30);
        break;
    }
  };

  // Helper to parse timestamp
  const extractTs = (s: any): number => {
    const raw = s.created_ts || s.created_at_utc || s.timestamp || s.created_at || s.detected_at || s.opened_at || s.evaluated_at_utc;
    if (typeof raw === "number") return raw < 1e11 ? raw * 1000 : raw;
    if (typeof raw === "string") {
      const parsed = new Date(raw).getTime();
      if (!isNaN(parsed) && parsed > 0) return parsed;
    }
    return Date.now();
  };

  // Helper to format horizon nicely
  const formatHorizonLabel = (rawHorizon: string): string => {
    const h = String(rawHorizon || "").trim().toUpperCase();
    if (h.includes("15M") || h.includes("SCALP")) return "⚡ Scalp (15M)";
    if (h.includes("1H") || h.includes("DAY TRADE") || h.includes("INTRADAY") || h.includes("SWING (1H)")) return "⏳ Day Trade (1H)";
    if (h.includes("24H") || h.includes("1D") || h.includes("SWING") || h.includes("MACRO")) return "🌊 Swing Trade (1D)";
    return rawHorizon || "⏳ Day Trade (1H)";
  };

  // Helper to map signal or trade outcome to NotificationType, Title and Message
  const mapSignalOutcome = (s: any): { type: NotificationType; title: string; message: string; pnl: number } => {
    const sym = s.symbol || "UNKNOWN";
    const rawHorizon = s.horizon_tag || s.horizon || s.horizon_name || "1H Intraday";
    const horizon = formatHorizonLabel(rawHorizon);
    const rawDir = (s.direction || (s.action ? (String(s.action).toUpperCase().includes("SHORT") ? "SHORT" : "LONG") : "LONG")).toUpperCase();
    const isShort = rawDir.includes("SHORT") || rawDir.includes("BEAR") || rawDir.includes("SELL");
    const direction = isShort ? "SHORT" : "LONG";

    const outcomeLabel = String(s.outcome || s.outcome_label || "").toUpperCase();
    const status = String(s.status || s.outcome_label || s.exit_reason || "ACTIVE").toUpperCase();
    const exitReason = String(s.exit_reason || "").toUpperCase();
    const decision = String(s.decision || s.pattern_name || s.pattern_type || s.strategy || "").toUpperCase();

    // Explicitly identify active/in-flight states (NEVER closed)
    const isActiveTrade = status.includes("ACTIVE") || 
                          status.includes("RUNNING") || 
                          status.includes("OPEN") || 
                          status.includes("RESTING") || 
                          outcomeLabel.includes("RUNNING") || 
                          outcomeLabel.includes("EVALUAT");

    // Strictly detect closed trades: requires explicit exit indicators and NOT being in active/running state
    const hasExitSignal = Boolean(
      (s.exit_price && Number(s.exit_price) > 0) ||
      (exitReason !== "") ||
      outcomeLabel.includes("WON") ||
      outcomeLabel.includes("LOST") ||
      outcomeLabel.includes("CLOSED") ||
      outcomeLabel.includes("EXIT") ||
      status.includes("CLOSED") ||
      status.includes("EXIT") ||
      status.includes("STOPPED")
    );
    const isClosedTrade = hasExitSignal && !isActiveTrade;
    const parsePnl = (val: any): number => {
      if (val === undefined || val === null || val === "") return NaN;
      if (typeof val === "number") return isNaN(val) ? NaN : val;
      const clean = String(val).replace(/[%+,\s]/g, "").trim();
      const n = parseFloat(clean);
      return isNaN(n) ? NaN : n;
    };

    const rawRealized = parsePnl(s.realized_return_num);
    const rawRealizedPct = parsePnl(s.realized_return_pct);
    const rawRealizedPnl = parsePnl(s.realized_pnl_pct);
    const rawPnl = parsePnl(s.pnl_pct);
    const rawLive = parsePnl(s.live_pnl_pct);

    const hasRealized = !isNaN(rawRealized) || !isNaN(rawRealizedPct) || !isNaN(rawRealizedPnl) || !isNaN(rawPnl);
    const realizedPnl = !isNaN(rawRealized) ? rawRealized : (!isNaN(rawRealizedPct) ? rawRealizedPct : (!isNaN(rawRealizedPnl) ? rawRealizedPnl : rawPnl));
    const pnl = hasRealized ? (realizedPnl ?? 0) : (!isNaN(rawLive) ? (rawLive ?? 0) : 0);
    const conv = Number(s.conviction || s.conviction_pct || 75);
    const grade = s.grade || s.quality_grade || (conv >= 80 ? "💎 Grade A+" : "🟢 Grade A");

    // 1. Explicit Loss or Stop-Loss Hit (Strictly when PnL is negative or labeled as LOST)
    const isLoss = outcomeLabel.includes("LOST") || status.includes("LOST") || status.includes("SL HIT") || (pnl < 0 && (status.includes("STOP_LOSS") || status.includes("STOPPED") || status.includes("CLOSED") || status.includes("EXIT") || status.includes("EXPIRED") || status.includes("EVALUATED")));
    if (isLoss) {
      const pnlStr = pnl !== 0 ? `${pnl.toFixed(2)}%` : "-2.50%";
      return {
        type: "SL_HIT",
        title: `🛑 Stop Loss Hit: ${sym} (${horizon})`,
        message: `Position closed at Stop Loss (${pnlStr}). Invalidation level respected.`,
        pnl: pnl !== 0 ? pnl : -2.5,
      };
    }

    // 2. Breakeven / Soft BE Early Protection (Tier-0 In-Trade Guard or Breakeven Exit)
    // CRITICAL: Evaluated before TP Hit so WON_TIER0_BE or Breakeven exits never trigger a false TP alert
    const isBreakeven = status.includes("TIER0") || status.includes("BREAKEVEN") || outcomeLabel.includes("BREAKEVEN") || outcomeLabel.includes("TIER-0") || status.includes("SOFT BE") || status.includes("GUARD");
    if (isBreakeven) {
      const pnlStr = pnl >= 0 ? `+${pnl.toFixed(2)}%` : `${pnl.toFixed(2)}%`;
      const isExit = isClosedTrade || status.includes("WON_TIER0_BE") || status.includes("HIT") || status.includes("CLOSED") || outcomeLabel.includes("BREAKEVEN");
      return {
        type: "BREAKEVEN_PROTECTED",
        title: isExit ? `🛡️ Breakeven Exit: ${sym} (${horizon})` : `🛡️ Breakeven Protected: ${sym} (${horizon})`,
        message: isExit
          ? `Trade closed at fee-covered Breakeven (${pnlStr}). Capital successfully preserved.`
          : `Stop Loss ratcheted to Breakeven (${pnlStr}). Capital protected against drawdown.`,
        pnl,
      };
    }

    // 3. Take Profit 1 / TP2 / TP3 Hit or Trailing Win (Strictly verified target hits, excluding Breakeven)
    const isTpHit = !isBreakeven && (
      outcomeLabel.includes("WON") || 
      status.includes("WON") || 
      status.includes("TP1_LOCKED") || 
      status.includes("TP2_LOCKED") || 
      (status.includes("TP3") && !status.includes("AWAITING")) || 
      (status.includes("TP2") && !status.includes("AWAITING")) || 
      (status.includes("TP1") && !status.includes("AWAITING")) || 
      outcomeLabel.includes("TP1") || 
      outcomeLabel.includes("TP2") || 
      outcomeLabel.includes("TP3") || 
      status.includes("TRAILING_SL")
    );
    if (isTpHit && (pnl > 0.05 || status.includes("WON") || outcomeLabel.includes("WON"))) {
      const pnlStr = pnl >= 0 ? `+${pnl.toFixed(2)}%` : `+0.00%`;
      const isTP1Locked = status.includes("TP1_LOCKED") || outcomeLabel.includes("TP1");
      const isTP2 = status.includes("TP2") || outcomeLabel.includes("TP2");
      const isTP3 = status.includes("TP3") || outcomeLabel.includes("TP3");
      const title = isTP3 ? `🏆 Target 3 (TP3) Won: ${sym} (${horizon})` : (isTP2 ? `🎯 Target 2 (TP2) Hit: ${sym} (${horizon})` : `🎯 Target 1 (TP1) Hit: ${sym} (${horizon})`);
      const message = isTP1Locked
        ? `Target 1 achieved (${pnlStr})! Stop Loss automatically raised to Breakeven (Trade is now Risk-Free).`
        : `Take Profit executed with ${pnlStr} return! Institutional target achieved.`;
      return {
        type: "TP_HIT",
        title,
        message,
        pnl,
      };
    }

    // 4. Horizon Expired
    if (status.includes("EXPIRED") || status.includes("EXPIRY")) {
      const pnlStr = pnl >= 0 ? `+${pnl.toFixed(2)}%` : `${pnl.toFixed(2)}%`;
      return {
        type: "EXPIRED",
        title: `⏱️ Horizon Expired: ${sym} (${horizon})`,
        message: `Timeframe completed (${pnlStr}). Position closed at candle close.`,
        pnl,
      };
    }

    // 4.5 Closed Trade Generic Fallback (Never treat a closed trade as a new signal; Never label 0% as TP_HIT)
    if (isClosedTrade) {
      const pnlStr = pnl >= 0 ? `+${pnl.toFixed(2)}%` : `${pnl.toFixed(2)}%`;
      if (pnl > 0.05 && (outcomeLabel.includes("WON") || status.includes("WON"))) {
        return {
          type: "TP_HIT",
          title: `🎯 Take Profit Hit: ${sym} (${horizon})`,
          message: `Position closed with ${pnlStr} realized return. Institutional target achieved.`,
          pnl,
        };
      }
      if (pnl < -0.05) {
        return {
          type: "SL_HIT",
          title: `🛑 Stop Loss Hit: ${sym} (${horizon})`,
          message: `Position closed with ${pnlStr} realized return. Invalidation level respected.`,
          pnl,
        };
      }
      return {
        type: "BREAKEVEN_PROTECTED",
        title: `🛡️ Breakeven Exit: ${sym} (${horizon})`,
        message: `Position closed with ${pnlStr} realized return. Capital protected.`,
        pnl,
      };
    }

    // 5. Sudden Hype Surge (Parabolic Momentum Pump)
    const isHype = s.is_hype_surge || decision.includes("HYPE") || decision.includes("PARABOLIC") || decision.includes("PUMP") || decision.includes("MOMENTUM SCALP");
    if (isHype && !isShort) {
      return {
        type: "HYPE_SURGE",
        title: `🚀 Sudden Hype Pump: ${sym} LONG (${horizon})`,
        message: `🔥 Parabolic volume breakout detected! Target: +${Math.abs(s.predicted_return_pct || s.expected_return_pct || 3.8).toFixed(2)}%`,
        pnl,
      };
    }

    // 6. Sudden Blow-Off Top (Exhaustion Sell / Climax Reversal Short)
    const isBlowoff = s.is_blowoff_top || decision.includes("BLOW-OFF") || decision.includes("EXHAUSTION") || decision.includes("TOP-REVERSAL") || decision.includes("FADE");
    if (isBlowoff || (isShort && (decision.includes("REVERSAL") || decision.includes("CLIMAX")))) {
      return {
        type: "BLOWOFF_TOP",
        title: `🛑 Sudden Blow-Off Top: ${sym} SHORT (${horizon})`,
        message: `⚡ Climax exhaustion reversal identified! Invalidation stop set above top wick. Target: +${Math.abs(s.predicted_return_pct || s.expected_return_pct || 3.5).toFixed(2)}%`,
        pnl,
      };
    }

    // 7. Standard Displayed Long / Short Signal
    return {
      type: "NEW_SIGNAL",
      title: isShort ? `🔴 New SHORT Signal: ${sym} (${horizon})` : `🟢 New LONG Signal: ${sym} (${horizon})`,
      message: `${grade} • Conviction: ${conv.toFixed(1)}% • Target Gain: +${Math.abs(s.predicted_return_pct || s.expected_return_pct || 2.5).toFixed(2)}%`,
      pnl,
    };
  };

  // Process live displayed signals & detect state transitions
  useEffect(() => {
    // Collect ONLY signals that are displayed to the user
    const displayedSignals: any[] = [];
    const seenLocalKeys = new Set<string>();

    // 1. Top Round Picks (Gold, Silver, Bronze dominant UI cards)
    if (forecastData?.top_round_signals && Array.isArray(forecastData.top_round_signals)) {
      for (const s of forecastData.top_round_signals) {
        const key = s.signal_id || `${s.symbol}-${s.horizon || s.horizon_tag || 'TOP'}`;
        if (!seenLocalKeys.has(key)) {
          seenLocalKeys.add(key);
          displayedSignals.push(s);
        }
      }
    }

    // 2. Horizon-by-Horizon displayed dominant signals (15M to 30D active cards)
    if (forecastData?.signals_by_horizon && typeof forecastData.signals_by_horizon === "object") {
      Object.values(forecastData.signals_by_horizon).forEach((list: any) => {
        if (Array.isArray(list)) {
          for (const s of list) {
            const key = s.signal_id || `${s.symbol}-${s.horizon || s.horizon_tag}`;
            if (!seenLocalKeys.has(key)) {
              seenLocalKeys.add(key);
              displayedSignals.push(s);
            }
          }
        }
      });
    }

    // 3. Active Institutional Signals (Displayed active tracker matrix)
    if (forecastData?.active_institutional_signals && Array.isArray(forecastData.active_institutional_signals)) {
      for (const s of forecastData.active_institutional_signals) {
        const key = s.signal_id || `${s.symbol}-${s.horizon || s.horizon_tag}`;
        if (!seenLocalKeys.has(key)) {
          seenLocalKeys.add(key);
          displayedSignals.push(s);
        }
      }
    }

    if (displayedSignals.length === 0 && (!portfolioData || !portfolioData.closed_trades_history)) return;

    const newNotifications: SignalNotification[] = [];

    // Process Displayed Signals
    for (const s of displayedSignals) {
      const sym = s.symbol || "UNKNOWN";
      const horizon = formatHorizonLabel(s.horizon_tag || s.horizon || s.horizon_name || "1H Swing");
      const rawDir = (s.direction || (s.action ? (String(s.action).toUpperCase().includes("SHORT") ? "SHORT" : "LONG") : "LONG")).toUpperCase();
      const isShort = rawDir.includes("SHORT") || rawDir.includes("BEAR") || rawDir.includes("SELL");
      const direction = isShort ? "SHORT" : "LONG";

      const sigKey = s.signal_id || `${sym}-${horizon}-${s.entry_price || s.raw_entry_price || 'BASE'}`;
      const prevStatus = prevSignalStatusMap.current.get(sigKey);
      const currentStatus = String(s.status || s.outcome_label || "ACTIVE").toUpperCase();

      const tsMs = extractTs(s);
      const tsStr = formatServerPredictionTime(new Date(tsMs));
      const entry = Number(s.entry_price || s.current_price || 0);
      const currP = Number(s.current_price || entry);
      const target = Number(s.tp1_price || s.tp_price || s.target_price || s.predicted_next_price || 0);
      const sl = Number(s.sl_price || 0);
      const conv = Number(s.conviction || s.conviction_pct || 75);
      const meta = Number(s.meta_win_prob ? s.meta_win_prob * 100 : s.meta_win_prob_pct || 70);
      const grade = s.grade || s.quality_grade || (conv >= 80 ? "💎 Grade A+" : "🟢 Grade A");

      const outcome = mapSignalOutcome(s);

      // 1. State Transitions (Active -> TP Hit / SL Hit / Expired)
      if (prevStatus && prevStatus !== currentStatus) {
        if (outcome.type !== "NEW_SIGNAL") {
          const item: SignalNotification = {
            id: `TRANS_${sigKey}_${Date.now()}`,
            type: outcome.type,
            title: outcome.title,
            message: outcome.message,
            symbol: sym,
            horizon,
            direction,
            entryPrice: entry,
            currentPrice: currP,
            targetPrice: target,
            stopLossPrice: sl,
            realizedPnlPct: outcome.pnl,
            conviction: conv,
            metaWinProb: meta,
            grade,
            status: currentStatus,
            timestamp: tsStr,
            timestampMs: Date.now(),
            isRead: false,
            rawSignal: s,
          };
          newNotifications.push(item);
        }
      }

      // 2. Fresh New Displayed Signals (Longs, Shorts, Hypes, Blow-offs)
      if (!seenSignalIds.current.has(sigKey)) {
        seenSignalIds.current.add(sigKey);

        if (!isInitialLoad.current) {
          const item: SignalNotification = {
            id: `NEW_${sigKey}`,
            type: outcome.type,
            title: outcome.title,
            message: outcome.message,
            symbol: sym,
            horizon,
            direction,
            entryPrice: entry,
            currentPrice: currP,
            targetPrice: target,
            stopLossPrice: sl,
            realizedPnlPct: outcome.pnl,
            conviction: conv,
            metaWinProb: meta,
            grade,
            status: currentStatus,
            timestamp: tsStr,
            timestampMs: tsMs,
            isRead: false,
            rawSignal: s,
          };
          newNotifications.push(item);
        }
      }

      prevSignalStatusMap.current.set(sigKey, currentStatus);
    }

    // Process Closed Trades from Paper Execution Bot
    if (portfolioData?.closed_trades_history && Array.isArray(portfolioData.closed_trades_history)) {
      if (isInitialPortfolioLoad.current) {
        // Seed initial history of closed trades so historical trades never trigger new alerts
        isInitialPortfolioLoad.current = false;
        for (const t of portfolioData.closed_trades_history) {
          const tradeId = t.trade_id || `TRADE_${t.symbol}_${t.exit_price}_${t.horizon}_${t.id || ''}`;
          seenClosedTradeIds.current.add(tradeId);
        }
      } else {
        for (const t of portfolioData.closed_trades_history) {
          const tradeId = t.trade_id || `TRADE_${t.symbol}_${t.exit_price}_${t.horizon}_${t.id || ''}`;
          if (!seenClosedTradeIds.current.has(tradeId)) {
            seenClosedTradeIds.current.add(tradeId);

            // Only notify if closed in real time during active session (within last 3 minutes)
            const closedAtMs = t.closed_at ? new Date(t.closed_at).getTime() : Date.now();
            if (Date.now() - closedAtMs <= 180000) {
              const sym = t.symbol || "UNKNOWN";
              const horizon = t.horizon || "Swing";
              const outcome = mapSignalOutcome(t);
              const tsMs = Date.now();

              const rawDir = String(t.direction_label || t.direction || "LONG").toUpperCase();
              const isShort = rawDir.includes("SHORT") || rawDir.includes("BEAR") || rawDir.includes("SELL");
              const direction: "LONG" | "SHORT" = isShort ? "SHORT" : "LONG";

              const item: SignalNotification = {
                id: `TRADE_CLOSE_${tradeId}`,
                type: outcome.type,
                title: outcome.title,
                message: outcome.message,
                symbol: sym,
                horizon,
                direction,
                entryPrice: Number(t.entry_price || 0),
                currentPrice: Number(t.exit_price || 0),
                targetPrice: Number((t as any).tp1_price || (t as any).tp_price || (t as any).target_price || 0),
                stopLossPrice: Number((t as any).sl_price || 0),
                realizedPnlPct: Number(t.realized_pnl_pct || outcome.pnl),
                timestamp: formatServerPredictionTime(new Date(tsMs)),
                timestampMs: tsMs,
                isRead: false,
                rawSignal: t,
              };
              newNotifications.push(item);
            }
          }
        }
      }
    }

    // Initial Load: Build activity history solely from active displayed signals
    if (isInitialLoad.current) {
      isInitialLoad.current = false;
      const initialItems: SignalNotification[] = displayedSignals.slice(0, 20).map((s, idx) => {
        const sym = s.symbol || "UNKNOWN";
        const horizon = formatHorizonLabel(s.horizon_tag || s.horizon || s.horizon_name || "1H Swing");
        const rawDir = (s.direction || (s.action ? (String(s.action).toUpperCase().includes("SHORT") ? "SHORT" : "LONG") : "LONG")).toUpperCase();
        const isShort = rawDir.includes("SHORT") || rawDir.includes("BEAR") || rawDir.includes("SELL");
        const tsMs = extractTs(s);
        const status = String(s.status || s.outcome_label || "ACTIVE").toUpperCase();
        const outcome = mapSignalOutcome(s);
        const conv = Number(s.conviction || s.conviction_pct || 75);

        return {
          id: `INIT_${sym}_${horizon}_${tsMs}_${idx}`,
          type: outcome.type,
          title: outcome.title,
          message: outcome.message,
          symbol: sym,
          horizon,
          direction: isShort ? "SHORT" : "LONG",
          entryPrice: Number(s.entry_price || s.current_price || 0),
          currentPrice: Number(s.current_price || s.entry_price || 0),
          targetPrice: Number(s.tp1_price || s.tp_price || s.target_price || s.predicted_next_price || 0),
          stopLossPrice: Number(s.sl_price || 0),
          realizedPnlPct: outcome.pnl,
          conviction: conv,
          metaWinProb: Number(
            s.meta_win_probability_pct ??
            (s.meta_win_probability !== undefined && s.meta_win_probability !== null
              ? (s.meta_win_probability <= 1.0 ? s.meta_win_probability * 100 : s.meta_win_probability)
              : (s.meta_win_prob_pct ?? (s.meta_win_prob ? (s.meta_win_prob <= 1.0 ? s.meta_win_prob * 100 : s.meta_win_prob) : 75)))
          ),
          grade: s.grade || s.quality_grade || (conv >= 80 ? "💎 Grade A+" : "🟢 Grade A"),
          status,
          timestamp: formatServerPredictionTime(new Date(tsMs)),
          timestampMs: tsMs,
          isRead: idx >= 3, // Mark first 3 as unread
          rawSignal: s,
        };
      });
      setNotifications(initialItems);
      // Do not popup toast on initial load; only populate drawer history
      return;
    }

    if (newNotifications.length > 0) {
      // Trigger Audio Chime on the newest notification
      const topNew = newNotifications[0];
      replaySound(topNew.type);

      // Show floating interactive toast
      setActiveToast(topNew);

      // Prepend to notifications list
      setNotifications((prev) => [...newNotifications, ...prev].slice(0, 50));
    }
  }, [forecastData, portfolioData]);

  const dismissActiveToast = () => {
    setActiveToast(null);
  };

  const markAsRead = (id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, isRead: true } : n))
    );
  };

  const markAllAsRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, isRead: true })));
  };

  const clearNotifications = () => {
    setNotifications([]);
  };

  const unreadCount = notifications.filter((n) => !n.isRead).length;

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        unreadCount,
        activeToast,
        dismissActiveToast,
        isDrawerOpen,
        setIsDrawerOpen,
        markAsRead,
        markAllAsRead,
        clearNotifications,
        soundEnabled,
        toggleSound,
        replaySound,
      }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotificationCenter() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error("useNotificationCenter must be used within a NotificationProvider");
  }
  return context;
}

