"use client";

import React from "react";
import { V16AuditEvent } from "@/types/v16";
import { History, Clock, FileText, CheckCircle2, Terminal } from "lucide-react";

interface Props {
  events: V16AuditEvent[];
  isLoading: boolean;
}

export default function V16EventJournal({ events, isLoading }: Props) {
  if (isLoading) {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-5 animate-pulse text-slate-500 font-mono text-xs flex items-center justify-center min-h-[220px]">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-cyan-400 animate-spin" />
          <span>Synchronizing immutable Section 54 event log stream...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/50 backdrop-blur-xl p-5 shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col justify-between">
      {/* Background ambient radial */}
      <div className="absolute -top-12 -left-12 w-48 h-48 bg-cyan-500/10 rounded-full blur-2xl pointer-events-none" />

      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3 relative z-10">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-cyan-950/60 border border-cyan-500/30 text-cyan-400">
            <History className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-bold tracking-wider text-white font-mono uppercase">
              Audit Event Journal
            </h2>
            <span className="text-[10px] text-slate-400 font-mono">Immutable Append-Only Audit Trail</span>
          </div>
        </div>
        <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-slate-950/80 border border-slate-700 text-slate-300">
          Section 54 Sourced
        </span>
      </div>

      {/* Events Stream */}
      <div className="my-3 space-y-2 max-h-[300px] overflow-y-auto pr-1 font-mono text-xs relative z-10">
        {events.length === 0 ? (
          <div className="py-8 px-4 rounded-xl border border-dashed border-slate-800 bg-slate-950/30 text-center text-slate-400 text-xs flex flex-col items-center justify-center gap-2">
            <Terminal className="w-5 h-5 text-slate-600" />
            <span className="font-bold text-slate-300">Awaiting New Lifecycle Events</span>
            <span className="text-[11px] text-slate-500">
              Audit transactions are immutably logged upon every signal generation, TP hit, or SL ratchet.
            </span>
          </div>
        ) : (
          events.slice(0, 15).map((ev) => {
            const isTp = ev.event_type.includes("TP");
            const isSl = ev.event_type.includes("SL") || ev.event_type.includes("STOP");
            const isGen = ev.event_type.includes("GEN") || ev.event_type.includes("CREATE");

            return (
              <div
                key={ev.event_id}
                className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/80 text-[11px] hover:border-cyan-500/30 transition-all duration-200"
              >
                <div className="flex items-center justify-between text-slate-400">
                  <span
                    className={`font-bold px-2 py-0.5 rounded-md text-[10px] border ${
                      isTp
                        ? "bg-emerald-950/60 text-emerald-300 border-emerald-500/30"
                        : isSl
                        ? "bg-rose-950/60 text-rose-300 border-rose-500/30"
                        : isGen
                        ? "bg-cyan-950/60 text-cyan-300 border-cyan-500/30"
                        : "bg-indigo-950/60 text-indigo-300 border-indigo-500/30"
                    }`}
                  >
                    {ev.event_type}
                  </span>
                  <span className="text-[10px] text-slate-400 flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3 text-slate-500" />
                    {ev.timestamp_utc}
                  </span>
                </div>
                <div className="text-slate-200 mt-1.5 font-sans leading-relaxed">{ev.detail}</div>
                <div className="text-[10px] text-slate-500 mt-1 truncate font-mono">
                  Signal Reference: <span className="text-slate-400">{ev.signal_id}</span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div className="pt-3 border-t border-slate-800/80 text-[10px] text-slate-500 font-mono flex items-center justify-between relative z-10">
        <span>Immutable Event Sourcing: Cryptographically Verifiable</span>
        <span className="text-emerald-400 flex items-center gap-1.5 font-bold">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Audit Compliant
        </span>
      </div>
    </div>
  );
}
