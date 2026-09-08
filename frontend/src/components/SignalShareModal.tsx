"use client";

import React, { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { formatUsd } from "@/lib/utils";
import {
  X,
  Copy,
  Check,
  Share2,
  Send,
  Zap,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";

interface SignalShareModalProps {
  signal: any;
  onClose: () => void;
}

export default function SignalShareModal({ signal, onClose }: SignalShareModalProps) {
  const [mounted, setMounted] = useState(false);
  const [copied, setCopied] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!signal || !mounted) return null;

  const symbol = signal.symbol || "BTC/USDT";
  const direction = (signal.direction || "LONG").toUpperCase();
  const isLong = direction.includes("LONG") || direction.includes("BULL");
  const horizon = signal.horizon || "SCALP (15M)";
  const grade = signal.quality_grade || signal.grade || "Grade A+";
  const conviction = signal.conviction_pct ?? signal.conviction ?? 85.0;
  const entry = signal.entry_price ?? signal.current_price ?? 0.0;
  const tp1 = signal.tp1_price ?? signal.tp_price ?? entry * 1.03;
  const tp2 = signal.tp2_price ?? tp1 * 1.02;
  const sl = signal.sl_price ?? entry * 0.98;
  const rr = signal.risk_reward_ratio || "1:2.0";
  const expReturn = signal.expected_return_pct ?? (signal.exp_return ? signal.exp_return * 100 : 3.5);

  const telegramText = `⚡ QUANT EDGE V15.0 AI • INSTITUTIONAL SIGNAL ⚡
━━━━━━━━━━━━━━━━━━━━
🎯 Pair: ${symbol} (${horizon})
📊 Direction: ${isLong ? "🟢 LONG BUY" : "🔴 SHORT SELL"}
💎 Grade: ${grade} (${conviction.toFixed(1)}% Conviction)
━━━━━━━━━━━━━━━━━━━━
📍 Entry: ${formatUsd(entry)}
🎯 Target 1 (TP1): ${formatUsd(tp1)}
🎯 Target 2 (TP2): ${formatUsd(tp2)}
🛑 Invalidation (SL): ${formatUsd(sl)}
⚖️ Risk:Reward: ${rr} | Exp. Return: +${Math.abs(expReturn).toFixed(2)}%
━━━━━━━━━━━━━━━━━━━━
🛡️ Evaluated via 8-Horizon ML Confluence Engine
🔗 https://bullsandbears.binaryunit.tech`;

  const handleCopyTelegram = async () => {
    try {
      await navigator.clipboard.writeText(telegramText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch (e) {
      console.error("Failed to copy text", e);
    }
  };

  return createPortal(
    <div
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-[100000] flex items-center justify-center bg-black/85 backdrop-blur-lg p-3 sm:p-4 animate-in fade-in duration-200"
    >
      <div className="relative w-full max-w-md rounded-2xl bg-dark-950 border border-slate-700/60 shadow-2xl shadow-cyan-950/40 overflow-hidden transform animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800/80 px-4 sm:px-5 py-3.5 bg-dark-900/90 backdrop-blur-md">
          <div className="flex items-center gap-2">
            <Share2 className="h-4 w-4 text-cyan-400" />
            <h3 className="text-sm font-black text-white">Export & Share Signal Ticket</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-white hover:bg-slate-800/80 transition-colors"
            title="Close (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* The Visual Ticket Card */}
        <div className="p-4 sm:p-5">
          <div
            ref={cardRef}
            className="relative rounded-2xl bg-gradient-to-br from-dark-900 via-dark-950 to-dark-900 p-4 sm:p-5 border border-cyan-500/30 shadow-xl overflow-hidden"
          >
            {/* Ambient Background Glow */}
            <div
              className={`absolute -top-10 -right-10 h-32 w-32 rounded-full blur-3xl pointer-events-none ${
                isLong ? "bg-emerald-500/20" : "bg-rose-500/20"
              }`}
            />

            {/* Brand Header */}
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-tr from-cyan-500 to-indigo-600 shadow-sm">
                  <Zap className="h-3.5 w-3.5 text-white" />
                </div>
                <div>
                  <span className="text-xs font-black tracking-wider text-white">
                    QUANT<span className="text-cyan-400">EDGE</span> AI
                  </span>
                  <p className="text-[9px] text-slate-400 font-mono">8-Horizon Confluence V15.0</p>
                </div>
              </div>

              <span className="rounded-full bg-cyan-950/80 px-2.5 py-0.5 text-[10px] font-bold text-cyan-300 border border-cyan-700/50">
                💎 {grade}
              </span>
            </div>

            {/* Symbol & Direction Banner */}
            <div className="mt-3.5 flex items-center justify-between">
              <div>
                <h4 className="text-xl sm:text-2xl font-black text-white">{symbol}</h4>
                <span className="text-xs text-slate-400 flex items-center gap-1 font-mono">
                  <Clock className="h-3 w-3 text-cyan-400" /> {horizon}
                </span>
              </div>

              <span
                className={`inline-flex items-center gap-1 rounded-xl px-3 py-1.5 text-xs font-black ${
                  isLong
                    ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                    : "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                }`}
              >
                {isLong ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
                {isLong ? "LONG BUY" : "SHORT SELL"}
              </span>
            </div>

            {/* Price Targets Matrix */}
            <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-dark-950/90 p-3 border border-slate-800/80 font-mono text-xs">
              <div>
                <span className="text-[10px] uppercase font-bold text-slate-400">Entry Price</span>
                <p className="text-white font-bold">{formatUsd(entry)}</p>
              </div>
              <div>
                <span className="text-[10px] uppercase font-bold text-rose-400">Stop-Loss (SL)</span>
                <p className="text-rose-400 font-bold">{formatUsd(sl)}</p>
              </div>
              <div className="border-t border-slate-800/60 pt-1.5">
                <span className="text-[10px] uppercase font-bold text-emerald-400">Target 1 (TP1)</span>
                <p className="text-emerald-400 font-bold">{formatUsd(tp1)}</p>
              </div>
              <div className="border-t border-slate-800/60 pt-1.5">
                <span className="text-[10px] uppercase font-bold text-emerald-300">Target 2 (TP2)</span>
                <p className="text-emerald-300 font-bold">{formatUsd(tp2)}</p>
              </div>
            </div>

            {/* Footer Watermark */}
            <div className="mt-3.5 flex items-center justify-between text-[10px] font-mono text-slate-400 border-t border-slate-800/60 pt-2">
              <span>Risk:Reward: <strong className="text-cyan-400">{rr}</strong></span>
              <span className="text-cyan-400 font-bold truncate max-w-[170px]">bullsandbears.binaryunit.tech</span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="mt-4 flex items-center gap-2">
            <button
              onClick={handleCopyTelegram}
              className="flex-1 flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-indigo-600 px-4 py-2.5 text-xs font-bold text-white hover:from-cyan-500 hover:to-indigo-500 transition-all shadow-lg shadow-cyan-500/20 active:scale-[0.98]"
            >
              {copied ? <Check className="h-4 w-4 text-emerald-300" /> : <Send className="h-4 w-4" />}
              {copied ? "Copied for Telegram!" : "Copy Telegram Alert"}
            </button>
            <button
              onClick={handleCopyTelegram}
              className="flex items-center gap-1.5 rounded-xl bg-dark-900 px-3.5 py-2.5 text-xs font-bold text-slate-300 border border-slate-800 hover:bg-slate-800 hover:text-white transition-all active:scale-[0.98]"
              title="Copy Formatted Text"
            >
              <Copy className="h-4 w-4" />
              Copy
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
