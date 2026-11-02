"use client";

import React, { useState } from "react";
import { useNotificationCenter } from "@/context/NotificationContext";
import {
  X,
  Zap,
  TrendingUp,
  TrendingDown,
  Target,
  ShieldAlert,
  ShieldCheck,
  Clock,
  Volume2,
  VolumeX,
  Trash2,
  CheckCheck,
  ChevronRight,
  Bell,
  Flame,
  AlertTriangle,
} from "lucide-react";
import { formatUsd } from "@/lib/utils";
import { NotificationType } from "@/types/notifications";

interface NotificationCenterDrawerProps {
  onSelectCoin?: (symbol: string) => void;
}

type FilterTab = "ALL" | "SIGNALS" | "HYPES" | "TP_HITS" | "BREAKEVEN" | "SL_HITS";

export default function NotificationCenterDrawer({ onSelectCoin }: NotificationCenterDrawerProps) {
  const {
    notifications,
    unreadCount,
    isDrawerOpen,
    setIsDrawerOpen,
    markAsRead,
    markAllAsRead,
    clearNotifications,
    soundEnabled,
    toggleSound,
    replaySound,
  } = useNotificationCenter();

  const [activeTab, setActiveTab] = useState<FilterTab>("ALL");

  // Keyboard shortcut to close drawer on Escape
  React.useEffect(() => {
    if (!isDrawerOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isDrawerOpen, setIsDrawerOpen]);

  if (!isDrawerOpen) return null;

  // Compute live counts per category tab
  const allCount = notifications.length;
  const signalsCount = notifications.filter(
    (n) => n.type === "NEW_SIGNAL" || n.direction === "LONG" || n.direction === "SHORT" || n.direction === "BULLISH" || n.direction === "BEARISH"
  ).length;
  const hypesCount = notifications.filter(
    (n) => n.type === "HYPE_SURGE" || n.type === "BLOWOFF_TOP"
  ).length;
  const tpHitsCount = notifications.filter((n) => n.type === "TP_HIT").length;
  const breakevenCount = notifications.filter((n) => n.type === "BREAKEVEN_PROTECTED").length;
  const slHitsCount = notifications.filter((n) => n.type === "SL_HIT").length;

  const filteredNotifications = notifications.filter((n) => {
    if (activeTab === "SIGNALS") return n.type === "NEW_SIGNAL" || n.direction === "LONG" || n.direction === "SHORT" || n.direction === "BULLISH" || n.direction === "BEARISH";
    if (activeTab === "HYPES") return n.type === "HYPE_SURGE" || n.type === "BLOWOFF_TOP";
    if (activeTab === "TP_HITS") return n.type === "TP_HIT";
    if (activeTab === "BREAKEVEN") return n.type === "BREAKEVEN_PROTECTED";
    if (activeTab === "SL_HITS") return n.type === "SL_HIT";
    return true;
  });

  const handleInspect = (symbol: string, id: string) => {
    markAsRead(id);
    setIsDrawerOpen(false);
    if (onSelectCoin) {
      onSelectCoin(symbol);
    } else {
      const cleanSym = symbol.replace("/", "_");
      const cardEl = document.getElementById(`signal-card-${cleanSym}`);
      const rowEl = document.getElementById(`asset-row-${cleanSym}`);
      const targetEl = cardEl || rowEl;
      if (targetEl) {
        targetEl.scrollIntoView({ behavior: "smooth", block: "center" });
        targetEl.classList.add("ring-2", "ring-cyan-400", "shadow-lg", "shadow-cyan-500/25");
        setTimeout(() => {
          targetEl.classList.remove("ring-2", "ring-cyan-400", "shadow-lg", "shadow-cyan-500/25");
        }, 3000);
      }
    }
  };

  const getIcon = (type: NotificationType, direction?: string) => {
    switch (type) {
      case "HYPE_SURGE":
        return <Flame className="w-4 h-4 text-amber-400" />;
      case "BLOWOFF_TOP":
        return <AlertTriangle className="w-4 h-4 text-rose-400" />;
      case "TP_HIT":
        return <Target className="w-4 h-4 text-emerald-400" />;
      case "SL_HIT":
        return <ShieldAlert className="w-4 h-4 text-red-400" />;
      case "BREAKEVEN_PROTECTED":
        return <ShieldCheck className="w-4 h-4 text-blue-400" />;
      case "EXPIRED":
        return <Clock className="w-4 h-4 text-amber-400" />;
      case "NEW_SIGNAL":
      default: {
        const isShort = direction === "SHORT" || direction === "BEARISH";
        return isShort ? (
          <TrendingDown className="w-4 h-4 text-red-400" />
        ) : (
          <TrendingUp className="w-4 h-4 text-emerald-400" />
        );
      }
    }
  };

  return (
    <div
      onClick={() => setIsDrawerOpen(false)}
      className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-in fade-in duration-200 cursor-pointer"
    >
      <div
        className="relative w-full max-w-lg bg-zinc-950 border-l border-zinc-800 shadow-2xl text-white flex flex-col h-full animate-in slide-in-from-right duration-300 cursor-default"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="p-4 sm:p-5 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 sm:p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 shrink-0">
              <Bell className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm sm:text-base font-black tracking-tight text-white flex items-center gap-2">
                Live Signal Activity Center
                {unreadCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-cyan-500 text-black text-[11px] font-black animate-pulse">
                    {unreadCount} New
                  </span>
                )}
              </h2>
              <p className="text-[11px] sm:text-xs text-zinc-400">
                Live alerts for displayed hypes, longs, shorts, TP & SL hits
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={toggleSound}
              title={soundEnabled ? "Audio Alerts: ON" : "Audio Alerts: OFF"}
              className={`p-2 rounded-xl border transition-colors ${
                soundEnabled
                  ? "bg-cyan-950/60 border-cyan-500/40 text-cyan-400"
                  : "bg-zinc-900 border-zinc-800 text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {soundEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            </button>
            <button
              onClick={() => setIsDrawerOpen(false)}
              className="p-2 rounded-xl bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-white transition-colors border border-zinc-800"
              title="Close (Esc)"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Filter Tabs & Bulk Actions */}
        <div className="px-3 sm:px-5 py-2.5 sm:py-3 border-b border-zinc-800/80 bg-zinc-900/40 flex items-center justify-between gap-2 overflow-x-auto touch-scroll no-scrollbar">
          <div className="flex items-center gap-1 sm:gap-1.5 shrink-0">
            {(["ALL", "SIGNALS", "HYPES", "TP_HITS", "BREAKEVEN", "SL_HITS"] as FilterTab[]).map((tab) => {
              const count =
                tab === "ALL"
                  ? allCount
                  : tab === "SIGNALS"
                  ? signalsCount
                  : tab === "HYPES"
                  ? hypesCount
                  : tab === "TP_HITS"
                  ? tpHitsCount
                  : tab === "BREAKEVEN"
                  ? breakevenCount
                  : slHitsCount;

              return (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                    activeTab === tab
                      ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                      : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200"
                  }`}
                >
                  <span>
                    {tab === "ALL" && "All"}
                    {tab === "SIGNALS" && "Signals (L/S)"}
                    {tab === "HYPES" && "🔥 Sudden Hypes"}
                    {tab === "TP_HITS" && "🎯 TP Wins"}
                    {tab === "BREAKEVEN" && "🛡️ Breakeven"}
                    {tab === "SL_HITS" && "🛑 SL Exits"}
                  </span>
                  <span
                    className={`rounded-full px-1.5 py-0.2 text-[10px] font-mono ${
                      activeTab === tab
                        ? "bg-cyan-950 text-cyan-200 border border-cyan-700/50"
                        : count > 0
                        ? "bg-zinc-800 text-zinc-300 font-bold"
                        : "bg-zinc-900 text-zinc-600"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-1 sm:gap-1.5 shrink-0">
            {unreadCount > 0 && (
              <button
                onClick={markAllAsRead}
                title="Mark all as read"
                className="px-2 py-1 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-cyan-300 transition-colors text-xs flex items-center gap-1 border border-zinc-800"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                <span className="hidden sm:inline text-[11px]">Mark read</span>
              </button>
            )}
            {notifications.length > 0 && (
              <button
                onClick={clearNotifications}
                title="Clear all notifications"
                className="p-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-red-400 transition-colors text-xs flex items-center gap-1 border border-zinc-800"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Notifications Stream */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2.5">
          {filteredNotifications.length === 0 ? (
            <div className="text-center py-16 text-zinc-500">
              <Bell className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p className="text-sm font-bold text-zinc-400">No notifications in this category</p>
              <p className="text-xs text-zinc-600 mt-1">
                Real-time trade and signal lifecycle events for displayed signals will appear here.
              </p>
            </div>
          ) : (
            filteredNotifications.map((n) => {
              const isHypeSurge = n.type === "HYPE_SURGE";
              const isBlowoffTop = n.type === "BLOWOFF_TOP";
              const isTpHit = n.type === "TP_HIT";
              const isSlHit = n.type === "SL_HIT";
              const isBreakeven = n.type === "BREAKEVEN_PROTECTED";
              const isExpired = n.type === "EXPIRED";

              return (
                <div
                  key={n.id}
                  onClick={() => markAsRead(n.id)}
                  className={`relative p-3.5 rounded-xl border transition-all cursor-pointer ${
                    !n.isRead ? "bg-zinc-900/90 border-cyan-500/30" : "bg-zinc-900/40 border-zinc-800/80"
                  } hover:border-zinc-700 hover:bg-zinc-900`}
                >
                  {/* Unread indicator dot */}
                  {!n.isRead && (
                    <span className="absolute top-3 right-3 w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
                  )}

                  <div className="flex items-start gap-3">
                    <div
                      className={`p-2 rounded-xl shrink-0 mt-0.5 ${
                        isHypeSurge
                          ? "bg-amber-500/10 border border-amber-500/30"
                          : isBlowoffTop
                          ? "bg-rose-500/10 border border-rose-500/30"
                          : isTpHit
                          ? "bg-emerald-500/10 border border-emerald-500/30"
                          : isSlHit
                          ? "bg-red-500/10 border border-red-500/30"
                          : isBreakeven
                          ? "bg-blue-500/10 border border-blue-500/30"
                          : isExpired
                          ? "bg-amber-500/10 border border-amber-500/30"
                          : (n.direction === "SHORT" || n.direction === "BEARISH")
                          ? "bg-red-500/10 border border-red-500/30"
                          : "bg-emerald-500/10 border border-emerald-500/30"
                      }`}
                    >
                      {getIcon(n.type, n.direction)}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono font-black text-sm text-white">{n.symbol}</span>
                        <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-white/10 text-zinc-300 uppercase">
                          {n.horizon}
                        </span>
                        {isHypeSurge ? (
                          <span className="text-[10px] font-black text-amber-400 bg-amber-500/20 px-1.5 py-0.5 rounded border border-amber-500/30">
                            🔥 HYPE
                          </span>
                        ) : isBlowoffTop ? (
                          <span className="text-[10px] font-black text-rose-400 bg-rose-500/20 px-1.5 py-0.5 rounded border border-rose-500/30">
                            🛑 BLOW-OFF
                          </span>
                        ) : (n.direction === "SHORT" || n.direction === "BEARISH") ? (
                          <span className="text-[10px] font-bold text-red-400">SHORT</span>
                        ) : (
                          <span className="text-[10px] font-bold text-emerald-400">LONG</span>
                        )}
                        <span className="text-[10px] text-zinc-500 ml-auto font-mono">{n.timestamp}</span>
                      </div>

                      <p className="mt-1 text-xs text-zinc-300 font-medium leading-snug">{n.message}</p>

                      {/* Stat Metrics Pill */}
                      <div className="mt-2 flex items-center gap-3 text-[11px] font-mono text-zinc-400 flex-wrap">
                        {n.entryPrice !== undefined && n.entryPrice > 0 && (
                          <span>
                            Entry: <b className="text-white">{formatUsd(n.entryPrice)}</b>
                          </span>
                        )}
                        {n.targetPrice !== undefined && n.targetPrice > 0 && (
                          <span>
                            TP: <b className="text-emerald-400">{formatUsd(n.targetPrice)}</b>
                          </span>
                        )}
                        {n.realizedPnlPct !== undefined && (
                          <span className={n.realizedPnlPct >= 0 ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
                            Return: {n.realizedPnlPct >= 0 ? `+${n.realizedPnlPct.toFixed(2)}%` : `${n.realizedPnlPct.toFixed(2)}%`}
                          </span>
                        )}
                      </div>

                      {/* Action Bar */}
                      <div className="mt-2.5 flex items-center justify-between pt-2 border-t border-zinc-800/60">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            replaySound(n.type);
                          }}
                          className="text-[11px] text-zinc-400 hover:text-white flex items-center gap-1"
                        >
                          <Volume2 className="w-3 h-3" /> Replay Sound
                        </button>

                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleInspect(n.symbol, n.id);
                          }}
                          className="text-[11px] font-bold text-cyan-400 hover:text-cyan-300 flex items-center gap-0.5"
                        >
                          Inspect <ChevronRight className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-zinc-800 text-xs text-zinc-400 flex items-center justify-between bg-zinc-900/40">
          <span>Active Displayed Signal Monitor</span>
          <span>{notifications.length} Total Alerts</span>
        </div>
      </div>
    </div>
  );
}

