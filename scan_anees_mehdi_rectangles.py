#!/usr/bin/env python3
"""
Quant Edge AI V16: Anees Mehdi 15M Rectangle Strategy Live Scanner
Scans the active cryptocurrency universe for 15M rectangle consolidation boxes,
recent liquidity sweeps, and confirmed breakout scalp signals.
"""

import os
import sys
import argparse
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

# Ensure root in path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.engine.scanner.data_loader import MultiHorizonDataLoader
from app.engine.scanner.filters import UniverseFilter
from app.quant_v16.rectangle_strategy import RectangleStrategyConfig, RectangleStrategyOrchestrator
from app.quant_v16.rectangle_strategy.rectangle_engine import RectangleStatus


def scan_universe(top_n: int = 50, verbose: bool = False):
    print("=" * 88)
    print(f"📐 ANEES MEHDI 15M RECTANGLE STRATEGY SCANNER (Top {top_n} Universe)")
    print(f"Scanning for M15 Liquidity Sweeps, Rectangle Boxes & Breakout Scalp Triggers...")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 88)

    dl = MultiHorizonDataLoader()
    cfg = RectangleStrategyConfig()
    orch = RectangleStrategyOrchestrator(cfg)

    universe = UniverseFilter.get_top_40_universe(top_n=top_n)
    symbols = [u["symbol"] for u in universe]

    active_boxes = []
    triggered_signals = []
    recent_sweeps = []

    for sym in symbols:
        try:
            df_15m = dl.fetch_single_timeframe_raw(sym, "15m", limit=100)
            if df_15m is None or len(df_15m) < 35:
                continue

            last_close = float(df_15m["close"].iloc[-1])

            # 1. Scan for setups across recent bars and current state
            res = orch.scan_for_setups(sym, df_15m, df_m1=None)
            status = res.get("signal_status")
            score = float(res.get("signal_score", 0.0))
            direction = res.get("direction")
            upper = float(res.get("rectangle_upper", 0.0))
            lower = float(res.get("rectangle_lower", 0.0))

            if status == "VALID":
                triggered_signals.append({
                    "symbol": sym,
                    "direction": direction,
                    "entry_price": res.get("entry_price"),
                    "stop_loss": res.get("stop_loss"),
                    "take_profit": res.get("take_profit"),
                    "risk_reward": res.get("risk_reward"),
                    "score": score,
                    "rectangle_upper": upper,
                    "rectangle_lower": lower,
                    "strategy": "THE_ONLY_1_MINUTE_RECTANGLE_STRATEGY"
                })
            elif upper > 0 and lower > 0:
                active_boxes.append({
                    "symbol": sym,
                    "direction": direction,
                    "current_price": last_close,
                    "rectangle_upper": upper,
                    "rectangle_lower": lower,
                    "score": score,
                    "status": "WAITING_FOR_BREAKOUT"
                })

            # Check if any recent sweeps occurred in last 8 bars
            for offset in range(-8, 0):
                sub_res = orch.scan_for_setups(sym, df_15m, df_m1=None, m15_bar_idx=offset)
                if sub_res.get("weakness_confirmed"):
                    recent_sweeps.append({
                        "symbol": sym,
                        "bar_offset": offset,
                        "direction": sub_res.get("direction"),
                        "upper": sub_res.get("rectangle_upper"),
                        "lower": sub_res.get("rectangle_lower"),
                        "score": sub_res.get("signal_score")
                    })
                    break

        except Exception as e:
            if verbose:
                print(f"[ERROR] {sym}: {e}")

    # Display Triggered Breakout Scalp Signals
    print("\n" + "=" * 88)
    print(f"⚡ CONFIRMED 15M RECTANGLE BREAKOUT SIGNALS ({len(triggered_signals)} Found)")
    print("=" * 88)
    if triggered_signals:
        header = f"{'Symbol':<12} {'Dir':<6} {'Entry':<12} {'Stop Loss':<12} {'Take Profit':<12} {'R:R':<8} {'Score':<6}"
        print(header)
        print("-" * len(header))
        for s in triggered_signals:
            print(f"{s['symbol']:<12} {s['direction']:<6} {str(s['entry_price']):<12} {str(s['stop_loss']):<12} {str(s['take_profit']):<12} {str(s['risk_reward']):<8} {s['score']:<6.1f}")
    else:
        print("No active breakout triggers on the current 15M bar. Monitoring active consolidation boxes...")

    # Display Active Consolidation Boxes Waiting for Breakout
    print("\n" + "=" * 88)
    print(f"📦 ACTIVE 15M RECTANGLE BOXES WAITING FOR BREAKOUT ({len(active_boxes)} Found)")
    print("=" * 88)
    if active_boxes:
        header = f"{'Symbol':<12} {'Dir':<6} {'Current Price':<14} {'Box Lower':<12} {'Box Upper':<12} {'Score':<6}"
        print(header)
        print("-" * len(header))
        for b in active_boxes:
            print(f"{b['symbol']:<12} {b['direction']:<6} {b['current_price']:<14.4f} {b['rectangle_lower']:<12.4f} {b['rectangle_upper']:<12.4f} {b['score']:<6.1f}")
    else:
        print("No active rectangles pending breakout.")

    # Display Recent Weakness Sweeps
    print("\n" + "=" * 88)
    print(f"🎯 RECENT 15M WEAKNESS SWEEPS (Last 8 Bars) ({len(recent_sweeps)} Found)")
    print("=" * 88)
    if recent_sweeps:
        header = f"{'Symbol':<12} {'Dir':<6} {'Bars Ago':<10} {'Box Lower':<12} {'Box Upper':<12} {'Score':<6}"
        print(header)
        print("-" * len(header))
        for sw in recent_sweeps:
            bars_ago = abs(sw['bar_offset'])
            print(f"{sw['symbol']:<12} {sw['direction']:<6} {bars_ago:<10} {sw['lower']:<12.4f} {sw['upper']:<12.4f} {sw['score']:<6.1f}")
    else:
        print("No recent sweeps detected in the lookback window.")

    # Save summary to export_app_data
    export_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "export_app_data"))
    os.makedirs(export_dir, exist_ok=True)
    report_path = os.path.join(export_dir, "active_rectangles_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "top_n": top_n,
            "triggered_signals": triggered_signals,
            "active_boxes": active_boxes,
            "recent_sweeps": recent_sweeps
        }, f, indent=2)
    print(f"\n[SCANNER 💾] Scan report saved to: {report_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Anees Mehdi 15M Rectangle Strategy Scanner")
    parser.add_argument("--top", type=int, default=40, help="Universe size (default: 40)")
    parser.add_argument("--verbose", action="store_true", help="Verbose error logging")
    args = parser.parse_args()
    scan_universe(top_n=args.top, verbose=args.verbose)

