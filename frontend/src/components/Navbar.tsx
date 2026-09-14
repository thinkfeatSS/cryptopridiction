"use client";

import React, { useMemo, useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useStatusQuery } from "@/hooks/useCryptoData";
import NavCountdownTimer from "@/components/NavCountdownTimer";
import HotkeysModal from "@/components/HotkeysModal";
import { useKeyboardHotkeys } from "@/hooks/useKeyboardHotkeys";
import {
  Activity,
  BarChart2,
  Clock,
  Database,
  Layers,
  ShieldCheck,
  ShieldAlert,
  TrendingUp,
  Zap,
  Volume2,
  VolumeX,
  Keyboard,
} from "lucide-react";
import { getShieldTheme } from "@/lib/marketShield";

export default function Navbar() {
  const pathname = usePathname();
  const { data: status } = useStatusQuery();
  const { showHotkeysModal, setShowHotkeysModal } = useKeyboardHotkeys();
  const [soundEnabled, setSoundEnabled] = useState<boolean>(true);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("quantedge_sound_enabled");
      if (stored !== null) {
        setSoundEnabled(stored === "true");
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  const toggleSound = () => {
    setSoundEnabled((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("quantedge_sound_enabled", String(next));
      } catch (e) {
        console.error(e);
      }
      return next;
    });
  };

  const navLinks = useMemo(
    () => [
      { href: "/", label: "Master Terminal", icon: Activity },
      { href: "/signals", label: "Signals Audit Ledger", icon: BarChart2 },
      { href: "/portfolio", label: "Paper Trading Bot", icon: TrendingUp },
      { href: "/radar", label: "Multi-Horizon Radar", icon: Layers },
    ],
    []
  );

  return (
    <>
      <HotkeysModal
        isOpen={showHotkeysModal}
        onClose={() => setShowHotkeysModal(false)}
      />

      <header className="sticky top-0 z-50 w-full border-b border-slate-800/80 bg-dark-950/95 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-3 py-2 sm:px-6 sm:py-3 gap-2">
          {/* Left: Brand / Strategy Title */}
          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            <div className="flex h-8 w-8 sm:h-10 sm:w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 shadow-lg shadow-cyan-500/20 shrink-0">
              <Zap className="h-4 w-4 sm:h-5 sm:w-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 sm:gap-2">
                <span className="text-base sm:text-lg font-black tracking-wider text-white">
                  QUANT<span className="text-cyan-400">EDGE</span>
                </span>
                <span className="rounded-md bg-cyan-950/80 px-1.5 py-0.2 sm:px-2 sm:py-0.5 text-[10px] sm:text-xs font-semibold text-cyan-300 border border-cyan-700/50">
                  V15.0 AI
                </span>
              </div>
              <p className="text-[10px] sm:text-[11px] text-slate-400 hidden xs:block">
                Multi-Horizon Confluence & Signal Engine
              </p>
            </div>
          </div>

          {/* Center: Navigation Links (Desktop & Tablet) */}
          <nav className="hidden lg:flex items-center gap-1 rounded-xl bg-dark-900/80 p-1 border border-slate-800/60">
            {navLinks.map((link) => {
              const Icon = link.icon;
              const isActive = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                    isActive
                      ? "bg-gradient-to-r from-cyan-500/20 to-indigo-500/20 text-cyan-300 border border-cyan-500/30 shadow-sm"
                      : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {link.label}
                </Link>
              );
            })}
          </nav>

          {/* Right Controls: Sound, Hotkeys, Shield, Timer, Daemon */}
          <div className="flex items-center gap-1.5 sm:gap-2.5">
            {/* Audio Alert Toggle */}
            <button
              onClick={toggleSound}
              className={`p-1.5 sm:p-2 rounded-xl border transition-all text-xs flex items-center justify-center shrink-0 ${
                soundEnabled
                  ? "bg-cyan-950/50 border-cyan-500/40 text-cyan-400 shadow-sm shadow-cyan-500/10"
                  : "bg-dark-900 border-slate-800 text-slate-500 hover:text-slate-300"
              }`}
              title={soundEnabled ? "Audio Alerts: ON (Chime on Grade A+ signals)" : "Audio Alerts: OFF"}
            >
              {soundEnabled ? <Volume2 className="h-3.5 w-3.5" /> : <VolumeX className="h-3.5 w-3.5" />}
            </button>

            {/* Hotkeys Modal Button */}
            <button
              onClick={() => setShowHotkeysModal(true)}
              className="hidden md:flex p-1.5 sm:p-2 rounded-xl border border-slate-800 bg-dark-900 text-slate-400 hover:text-cyan-300 hover:border-slate-700 transition-all text-xs shrink-0"
              title="Keyboard Shortcuts (?)"
            >
              <Keyboard className="h-3.5 w-3.5" />
            </button>

            {/* 🛡️ Market Beta Status Badge */}
            {(() => {
              const shieldTheme = getShieldTheme(status?.btc_market_shield);
              return (
                <div
                  className={`flex items-center gap-1.5 sm:gap-2 rounded-lg border px-2 sm:px-3 py-1 sm:py-1.5 text-xs shadow-sm transition-all shrink-0 ${shieldTheme.border}`}
                  title={`${shieldTheme.headline}: ${shieldTheme.subline}`}
                >
                  {shieldTheme.isAlert ? (
                    <ShieldAlert className={`h-3.5 w-3.5 sm:h-4 sm:w-4 ${shieldTheme.iconColor} shrink-0 animate-bounce`} />
                  ) : (
                    <ShieldCheck className={`h-3.5 w-3.5 sm:h-4 sm:w-4 ${shieldTheme.iconColor} shrink-0`} />
                  )}
                  <div className="flex flex-col">
                    <span className="text-[8px] sm:text-[9px] uppercase tracking-wider font-bold text-slate-400 flex items-center gap-1">
                      <span className="hidden xs:inline">[SHIELD 🛡️]</span> {shieldTheme.regimeBadge}
                      <span className={`inline-block h-1.5 w-1.5 rounded-full ${shieldTheme.dotColor}`} />
                    </span>
                    <span className="font-mono text-[10px] sm:text-[11px] font-bold truncate max-w-[80px] xs:max-w-[120px] sm:max-w-[170px]">
                      {shieldTheme.statusTitle}
                    </span>
                  </div>
                </div>
              );
            })()}

            {/* 15-min Countdown Ring / Badge */}
            <div className="shrink-0">
              <NavCountdownTimer />
            </div>

            {/* Bot State Indicator */}
            <div className="hidden 2xl:flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-950/30 px-3 py-1.5 text-xs text-emerald-400 shrink-0">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
              </span>
              <span className="font-semibold text-[11px] uppercase tracking-wider">
                Live Daemon Active
              </span>
            </div>
          </div>
        </div>

        {/* Mobile & Tablet Navigation Bar */}
        <div className="flex lg:hidden border-t border-slate-800/60 bg-dark-900/95 px-1 py-1 justify-around overflow-x-auto touch-scroll">
          {navLinks.map((link) => {
            const Icon = link.icon;
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`flex items-center sm:flex-row flex-col gap-1 py-1.5 px-2.5 sm:px-3 text-[11px] font-semibold rounded-lg transition-all ${
                  isActive
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-bold"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="whitespace-nowrap">{link.label}</span>
              </Link>
            );
          })}
        </div>
      </header>
    </>
  );
}
