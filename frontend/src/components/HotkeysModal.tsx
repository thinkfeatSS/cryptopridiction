"use client";

import React from "react";
import { X, Keyboard, Command } from "lucide-react";

interface HotkeysModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function HotkeysModal({ isOpen, onClose }: HotkeysModalProps) {
  if (!isOpen) return null;

  const hotkeys = [
    { key: "/", desc: "Focus Quick Search input" },
    { key: "1", desc: "Navigate to Master Terminal" },
    { key: "2", desc: "Navigate to Signals Audit Ledger" },
    { key: "3", desc: "Navigate to Paper Trading Bot" },
    { key: "4", desc: "Navigate to Multi-Horizon Radar" },
    { key: "ESC", desc: "Close any active modal popup" },
    { key: "?", desc: "Toggle this Keyboard Shortcuts cheat sheet" },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="relative w-full max-w-md rounded-2xl bg-dark-950 border border-slate-800 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-800/80 px-5 py-3.5 bg-dark-900/80">
          <div className="flex items-center gap-2">
            <Keyboard className="h-4 w-4 text-cyan-400" />
            <h3 className="text-sm font-black text-white">Pro Trader Hotkeys</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-2.5">
          {hotkeys.map((hk) => (
            <div
              key={hk.key}
              className="flex items-center justify-between rounded-xl bg-dark-900/60 p-2.5 border border-slate-800/60"
            >
              <span className="text-xs text-slate-300">{hk.desc}</span>
              <kbd className="rounded-lg bg-dark-950 px-2 py-1 text-xs font-mono font-black text-cyan-400 border border-slate-700 shadow-sm">
                {hk.key}
              </kbd>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
