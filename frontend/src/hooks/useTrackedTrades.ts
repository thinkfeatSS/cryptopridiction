"use client";

import { useState, useEffect, useCallback } from "react";

export interface TrackedTrade {
  id: string; // e.g. BTC/USDT_1H_1728450000
  symbol: string;
  direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH" | string;
  horizon: string;
  quality_grade: string;
  meta_win_prob_pct?: number;
  entry_price: number;
  current_price: number;
  tp1_price: number;
  tp2_price?: number;
  tp3_price?: number;
  sl_price: number;
  initial_sl_price: number;
  taken_at_utc: string;
  taken_timestamp: number;
  expires_at_utc?: string;
  expires_timestamp?: number;
  status: "ACTIVE" | "WON_TP1" | "WON_TP2" | "WON_TP3" | "WON_EXPIRED" | "LOST_SL" | "LOST_EXPIRED" | "BREAKEVEN" | "MANUALLY_CLOSED";
  realized_pnl_pct?: number;
  closed_at_utc?: string;
  outcome_label?: string;
  user_note?: string;
}

const STORAGE_KEY = "quantedge_user_tracked_trades_v1";

export function useTrackedTrades() {
  const [trackedTrades, setTrackedTrades] = useState<TrackedTrade[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setTrackedTrades(JSON.parse(stored));
      }
    } catch (e) {
      console.error("Failed to load tracked trades from localStorage", e);
    } finally {
      setIsLoaded(true);
    }
  }, []);

  // Save changes to localStorage
  const persistTrades = useCallback((trades: TrackedTrade[]) => {
    setTrackedTrades(trades);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(trades));
    } catch (e) {
      console.error("Failed to persist tracked trades", e);
    }
  }, []);

  // Track a new signal
  const takeTrade = useCallback(
    (signal: any, customEntry?: number, userNote?: string) => {
      const now = new Date();
      const symbol = signal.symbol || "BTC/USDT";
      const horizon = signal.horizon || "1H Intraday";
      const id = signal.signal_id || `${symbol.replace("/", "")}_${horizon}_${Date.now()}`;

      const entryPrice = Number(customEntry || signal.entry_price || signal.current_price || 0);
      const tp1 = Number(signal.tp1_price || signal.tp_price || entryPrice * 1.015);
      const tp2 = Number(signal.tp2_price || entryPrice * 1.03);
      const tp3 = Number(signal.tp3_price || entryPrice * 1.05);
      const sl = Number(signal.sl_price || entryPrice * 0.985);

      const isLong = signal.direction === "LONG" || signal.direction === "BULLISH";
      
      // Calculate approximate expiry timestamp if horizon string is known
      let horizonMs = 60 * 60 * 1000; // default 1H
      const hUpper = String(horizon).toUpperCase();
      if (hUpper.includes("15M") || hUpper.includes("SCALP")) horizonMs = 15 * 60 * 1000;
      else if (hUpper.includes("1H") || hUpper.includes("DAY TRADE") || hUpper.includes("INTRADAY")) horizonMs = 60 * 60 * 1000;
      else if (hUpper.includes("24H") || hUpper.includes("1D") || hUpper.includes("SWING") || hUpper.includes("MACRO")) horizonMs = 24 * 60 * 60 * 1000;

      const expiresTimestamp = Date.now() + horizonMs;
      const expiresAtUtc = new Date(expiresTimestamp).toISOString().replace("T", " ").substring(0, 19) + " UTC";

      const newTrade: TrackedTrade = {
        id,
        symbol,
        direction: isLong ? "LONG" : "SHORT",
        horizon,
        quality_grade: signal.quality_grade || signal.grade || "Grade A",
        meta_win_prob_pct: signal.meta_win_prob_pct ?? (signal.meta_win_prob ? signal.meta_win_prob * 100 : undefined),
        entry_price: entryPrice,
        current_price: Number(signal.current_price || entryPrice),
        tp1_price: tp1,
        tp2_price: tp2,
        tp3_price: tp3,
        sl_price: sl,
        initial_sl_price: sl,
        taken_at_utc: now.toISOString().replace("T", " ").substring(0, 19) + " UTC",
        taken_timestamp: Date.now(),
        expires_at_utc: signal.predicted_close_utc || expiresAtUtc,
        expires_timestamp: expiresTimestamp,
        status: "ACTIVE",
        user_note: userNote || "",
      };

      setTrackedTrades((prev) => {
        // If already taken, update it
        const exists = prev.some((t) => t.id === id);
        let updated: TrackedTrade[];
        if (exists) {
          updated = prev.map((t) => (t.id === id ? { ...t, ...newTrade } : t));
        } else {
          updated = [newTrade, ...prev];
        }
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
        } catch (e) {
          console.error(e);
        }
        return updated;
      });

      return newTrade;
    },
    []
  );

  // Check if a signal is currently tracked
  const isTradeTracked = useCallback(
    (signalIdOrSymbol: string) => {
      return trackedTrades.some(
        (t) => (t.id === signalIdOrSymbol || t.symbol === signalIdOrSymbol) && t.status === "ACTIVE"
      );
    },
    [trackedTrades]
  );

  // Manually close a trade
  const closeTrade = useCallback(
    (tradeId: string, currentPrice?: number, reason?: string) => {
      setTrackedTrades((prev) => {
        const updated = prev.map((trade) => {
          if (trade.id !== tradeId) return trade;
          const exitPrice = currentPrice || trade.current_price || trade.entry_price;
          const isLong = trade.direction === "LONG" || trade.direction === "BULLISH" || (trade as any).direction_label === "LONG";
          const pnlPct = trade.entry_price > 0
            ? isLong
              ? ((exitPrice - trade.entry_price) / trade.entry_price) * 100
              : ((trade.entry_price - exitPrice) / trade.entry_price) * 100
            : 0;

          const nowUtc = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";
          return {
            ...trade,
            status: (pnlPct > 0.1 ? "WON_EXPIRED" : pnlPct < -0.1 ? "LOST_EXPIRED" : "BREAKEVEN") as any,
            realized_pnl_pct: pnlPct,
            current_price: exitPrice,
            closed_at_utc: nowUtc,
            outcome_label: reason || `Manual Exit (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%)`,
          };
        });
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
        } catch (e) {
          console.error(e);
        }
        return updated;
      });
    },
    []
  );

  // Update live prices and evaluate TP/SL for tracked active trades
  const syncWithLivePrices = useCallback(
    (priceMap: Record<string, number>) => {
      if (!priceMap || Object.keys(priceMap).length === 0) return;

      setTrackedTrades((prev) => {
        let changed = false;
        const now = Date.now();

        const updated = prev.map((trade) => {
          if (trade.status !== "ACTIVE") return trade;

          const cleanSym = trade.symbol.toUpperCase().replace("/", "").replace(":USDT", "");
          const livePrice = priceMap[cleanSym] || priceMap[trade.symbol] || trade.current_price;
          if (!livePrice || livePrice <= 0) return trade;

          const isLong = trade.direction === "LONG" || trade.direction === "BULLISH" || (trade as any).direction_label === "LONG";
          const pnlPct = trade.entry_price > 0
            ? isLong
              ? ((livePrice - trade.entry_price) / trade.entry_price) * 100
              : ((trade.entry_price - livePrice) / trade.entry_price) * 100
            : 0;

          let newStatus: TrackedTrade["status"] = trade.status;
          let outcomeLabel = trade.outcome_label;
          let realizedPnl = trade.realized_pnl_pct;
          let closedAt = trade.closed_at_utc;
          let currentSl = trade.sl_price;

          // 1. Check TP3
          if (trade.tp3_price && (isLong ? livePrice >= trade.tp3_price : livePrice <= trade.tp3_price)) {
            newStatus = "WON_TP3";
            outcomeLabel = `🟢 Target 3 Reached (+${pnlPct.toFixed(2)}%)`;
            realizedPnl = pnlPct;
            closedAt = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";
            changed = true;
          }
          // 2. Check TP2
          else if (trade.tp2_price && (isLong ? livePrice >= trade.tp2_price : livePrice <= trade.tp2_price)) {
            newStatus = "WON_TP2";
            outcomeLabel = `🟢 Target 2 Reached (+${pnlPct.toFixed(2)}%)`;
            realizedPnl = pnlPct;
            closedAt = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";
            changed = true;
          }
          // 3. Check TP1 -> If hit, move SL to Entry (Break-even guard)
          else if (trade.tp1_price && (isLong ? livePrice >= trade.tp1_price : livePrice <= trade.tp1_price)) {
            if (currentSl !== trade.entry_price) {
              currentSl = trade.entry_price; // Shift SL to entry
              outcomeLabel = "🛡️ TP1 Hit • Break-Even Guard Active";
              changed = true;
            }
          }
          // 4. Check SL Hit
          else if (isLong ? livePrice <= currentSl : livePrice >= currentSl) {
            const isBe = Math.abs(currentSl - trade.entry_price) / trade.entry_price < 0.001;
            newStatus = isBe ? "BREAKEVEN" : "LOST_SL";
            outcomeLabel = isBe ? "⚪ Protected Break-Even Exit" : `🔴 Stop Loss Triggered (${pnlPct.toFixed(2)}%)`;
            realizedPnl = pnlPct;
            closedAt = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";
            changed = true;
          }
          // 5. Check Expiry
          else if (trade.expires_timestamp && now >= trade.expires_timestamp) {
            if (pnlPct >= 0.15) {
              newStatus = "WON_EXPIRED";
              outcomeLabel = `🟢 Horizon Expired in Profit (+${pnlPct.toFixed(2)}%)`;
            } else if (pnlPct <= -0.15) {
              newStatus = "LOST_EXPIRED";
              outcomeLabel = `🔴 Horizon Expired in Loss (${pnlPct.toFixed(2)}%)`;
            } else {
              newStatus = "BREAKEVEN";
              outcomeLabel = `⚪ Horizon Expired Flat (0.00%)`;
            }
            realizedPnl = pnlPct;
            closedAt = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";
            changed = true;
          }

          if (livePrice !== trade.current_price || changed) {
            return {
              ...trade,
              current_price: livePrice,
              sl_price: currentSl,
              status: newStatus,
              realized_pnl_pct: realizedPnl,
              outcome_label: outcomeLabel,
              closed_at_utc: closedAt,
            };
          }

          return trade;
        });

        if (changed) {
          try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
          } catch (e) {
            console.error(e);
          }
        }

        return updated;
      });
    },
    []
  );

  // Remove a trade from tracker
  const removeTrade = useCallback((tradeId: string) => {
    setTrackedTrades((prev) => {
      const updated = prev.filter((t) => t.id !== tradeId);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      } catch (e) {
        console.error(e);
      }
      return updated;
    });
  }, []);

  // Clear all resolved trades
  const clearResolvedTrades = useCallback(() => {
    setTrackedTrades((prev) => {
      const updated = prev.filter((t) => t.status === "ACTIVE");
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      } catch (e) {
        console.error(e);
      }
      return updated;
    });
  }, []);

  const activeTrades = trackedTrades.filter((t) => t.status === "ACTIVE");
  const closedTrades = trackedTrades.filter((t) => t.status !== "ACTIVE");

  return {
    trackedTrades,
    activeTrades,
    closedTrades,
    isLoaded,
    takeTrade,
    isTradeTracked,
    closeTrade,
    removeTrade,
    clearResolvedTrades,
    syncWithLivePrices,
  };
}
