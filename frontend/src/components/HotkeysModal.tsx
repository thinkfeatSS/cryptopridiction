"use client";

import React from "react";
import { X, Keyboard, Command, Sparkles, Navigation, Search, HelpCircle } from "lucide-react";

interface HotkeysModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function HotkeysModal({ isOpen, onClose }: HotkeysModalProps) {
  if (!isOpen) return null;

  const hotkeys = [
    { key: "/", desc: "Focus Coin Search Filter", icon: Search, category: "Search" },
    { key: "1", desc: "Master Terminal Dashboard", icon: Navigation, category: "Navigation" },
    { key: "2", desc: "Signals Audit Ledger & Journal", icon: Navigation, category: "Navigation" },
    { key: "3", desc: "Paper Trading Bot Portfolio", icon: Navigation, category: "Navigation" },
    { key: "4", desc: "Multi-Horizon Confluence Radar", icon: Navigation, category: "Navigation" },
    { key: "ESC", desc: "Close Any Active Modal / Popup", icon: X, category: "General" },
    { key: "?", desc: "Toggle Hotkeys Cheat Sheet", icon: HelpCircle, category: "General" },
  ];

  return (
    <div
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-lg p-3 sm:p-4 animate-in fade-in duration-200"
    >
      <div className="relative w-full max-w-md rounded-2xl bg-dark-950 border border-slate-700/60 shadow-2xl shadow-cyan-950/40 overflow-hidden transform animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800/80 px-4 sm:px-5 py-3.5 bg-dark-900/90 backdrop-blur-md">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-cyan-950 border border-cyan-700/50 text-cyan-400">
              <Keyboard className="h-4 w-4" />
            </span>
            <div>
              <h3 className="text-sm font-black text-white">Pro Terminal Shortcuts</h3>
              <p className="text-[10px] text-slate-400">Instant Navigation & Speed Commands</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-white hover:bg-slate-800/80 transition-colors"
            title="Close (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Hotkeys List */}
        <div className="p-4 sm:p-5 space-y-2">
          {hotkeys.map((hk) => {
            const Icon = hk.icon;
            return (
              <div
                key={hk.key}
                className="flex items-center justify-between rounded-xl bg-dark-900/70 hover:bg-dark-900 px-3.5 py-2.5 border border-slate-800/70 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <Icon className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
                  <span className="text-xs font-medium text-slate-300">{hk.desc}</span>
                </div>
                <kbd className="rounded-lg bg-dark-950 px-2.5 py-1 text-xs font-mono font-black text-cyan-400 border border-cyan-900/60 shadow-sm min-w-[28px] text-center">
                  {hk.key}
                </kbd>
              </div>
            );
          })}
        </div>

        {/* Footer Hint */}
        <div className="border-t border-slate-800/60 bg-dark-900/50 px-4 py-2.5 text-center text-[11px] text-slate-500 font-mono">
          Press <span className="text-slate-300 font-bold">Esc</span> or click outside to dismiss
        </div>
      </div>
    </div>
  );
}
