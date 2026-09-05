"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useStatusQuery } from "@/hooks/useCryptoData";
import { formatTimeRemaining } from "@/lib/utils";
import {
  Activity,
  BarChart2,
  Clock,
  Database,
  Layers,
  Radio,
  ShieldCheck,
  TrendingUp,
  Zap,
} from "lucide-react";

export default function Navbar() {
  const pathname = usePathname();
  const { data: status } = useStatusQuery();
  const [utcTime, setUtcTime] = useState<string>("");
  const [localSeconds, setLocalSeconds] = useState<number>(0);

  // Sync and tick down the 15-minute countdown clock
  useEffect(() => {
    if (status?.seconds_to_next_scan !== undefined) {
      setLocalSeconds(status.seconds_to_next_scan);
    }
  }, [status?.seconds_to_next_scan]);

  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date();
      setUtcTime(now.toUTCString().replace("GMT", "UTC"));
      setLocalSeconds((prev) => (prev > 0 ? prev - 1 : 900));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const navLinks = [
    { href: "/", label: "Master Terminal", icon: Activity },
    { href: "/signals", label: "Signals Audit Ledger", icon: BarChart2 },
    { href: "/portfolio", label: "Paper Trading Bot", icon: TrendingUp },
    { href: "/radar", label: "Multi-Horizon Radar", icon: Layers },
  ];

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-800/80 bg-dark-950/90 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
        {/* Left: Brand / Strategy Title */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 shadow-lg shadow-cyan-500/20">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-black tracking-wider text-white">
                QUANT<span className="text-cyan-400">EDGE</span>
              </span>
              <span className="rounded-md bg-cyan-950/80 px-2 py-0.5 text-xs font-semibold text-cyan-300 border border-cyan-700/50">
                V15.0 AI
              </span>
            </div>
            <p className="text-[11px] text-slate-400">
              Multi-Horizon Confluence & Signal Engine
            </p>
          </div>
        </div>

        {/* Center: Navigation Links */}
        <nav className="hidden md:flex items-center gap-1 rounded-xl bg-dark-900/80 p-1 border border-slate-800/60">
          {navLinks.map((link) => {
            const Icon = link.icon;
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-all ${
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

        {/* Right: Live UTC Clock & 15-Minute Scan Countdown */}
        <div className="flex items-center gap-3">
          {/* 15-min Countdown Ring / Badge */}
          <div className="flex items-center gap-2 rounded-lg border border-indigo-500/30 bg-indigo-950/40 px-3 py-1.5 text-xs shadow-sm shadow-indigo-500/10">
            <Radio className="h-3.5 w-3.5 animate-pulse text-indigo-400" />
            <div className="flex flex-col">
              <span className="text-[9px] uppercase tracking-wider text-indigo-300/80 font-bold">
                Next 15M Scan In
              </span>
              <span className="font-mono text-xs font-bold text-white">
                {formatTimeRemaining(localSeconds)}
              </span>
            </div>
          </div>

          {/* Bot State Indicator */}
          <div className="hidden sm:flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-950/30 px-3 py-1.5 text-xs text-emerald-400">
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

      {/* Mobile Navigation Bar */}
      <div className="flex md:hidden border-t border-slate-800/60 bg-dark-900/90 px-2 py-1 justify-around">
        {navLinks.map((link) => {
          const Icon = link.icon;
          const isActive = pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex flex-col items-center gap-0.5 py-1 px-2 text-[10px] font-medium ${
                isActive ? "text-cyan-400 font-bold" : "text-slate-400"
              }`}
            >
              <Icon className="h-4 w-4" />
              {link.label.split(" ")[0]}
            </Link>
          );
        })}
      </div>
    </header>
  );
}
