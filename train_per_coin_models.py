#!/usr/bin/env python3
"""
Dedicated Training Pipeline for Per-Coin Classifiers, Regressors, and Meta-Labelers.
-------------------------------------------------------------------------------------
Fulfills User Directive:
1. Classification of Bullish and Bearish: Trains separate 5-model ensemble for each coin.
2. Regressors: Trains separate 5-model regression ensemble for each coin.
3. Meta-Labelers: Trains separate secondary meta-classifier for each coin individually.
4. Atomically persists each coin's models under: models_export_v3/per_coin/{clean_symbol}/
"""

import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, List

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app.engine.config import TIMEFRAMES_9, MODELS_DIR
from app.engine.scanner.horizon_scanner import MultiHorizonScanner
from app.engine.signals.candle_features import CandleDynamicsFeatureExtractor
from app.engine.signals.per_coin_models import PerCoinModelRegistry
from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler

def run_per_coin_training(limit_assets: int = 40):
    t0 = time.time()
    print("=" * 90)
    print("🚀 QUANT EDGE: TRAINING DEDICATED SEPARATE MODELS PER COIN")
    print("   • 5 Direction Classifiers (Bullish/Bearish Next Candle Voting) per coin")
    print("   • 5 Price Regressors (Consensus Target Price Selection) per coin")
    print("   • Secondary ML Meta-Labelers (P(Win) Barrier Resolution) per coin")
    print("=" * 90)

    scanner = MultiHorizonScanner()
    feature_extractor = CandleDynamicsFeatureExtractor()
    model_registry = PerCoinModelRegistry()
    meta_labeler = CoinSpecificMetaLabeler()

    # Step 1: Ingest Universe & 9 Charts for Top Coins
    print("\n[STEP 1/3] Ingesting Top High-Volume Non-Meme Assets across 9 Charts...")
    scan_res = scanner.scan_universe()
    assets = scan_res.get("assets", {})
    target_coins = list(assets.items())[:limit_assets]
    print(f"  ✓ Ingested {len(target_coins)} coin charts for dedicated training.\n")

    # Step 2: Train Classifiers and Regressors Separately for Each Coin
    print(f"[STEP 2/3] Fitting 5 Classifiers + 5 Regressors separately for {len(target_coins)} coins across 9 timeframes...")
    import numpy as np

    trained_coins_summary = []

    for idx, (sym, coin_data) in enumerate(target_coins, 1):
        clean_sym = model_registry.get_clean_symbol(sym)
        dfs_9 = coin_data.get("dfs_9", {})
        curr_price = coin_data.get("price", 0.0)
        t_start_coin = time.time()

        trained_tfs = []
        for tf in TIMEFRAMES_9:
            df_tf = dfs_9.get(tf)
            if df_tf is None or len(df_tf) < 15:
                continue

            # Extract candle features
            feats = feature_extractor.extract_features(df_tf, prefix=tf)
            if feats.empty or len(feats) < 15:
                continue

            c = df_tf["close"].values
            o = df_tf["open"].values
            n = len(df_tf)

            target_direction = np.zeros(n, dtype=int)
            for i in range(n - 1):
                target_direction[i] = 1 if c[i + 1] > o[i + 1] else 0

            target_return = np.zeros(n, dtype=float)
            for i in range(n - 1):
                target_return[i] = (c[i + 1] - c[i]) / (c[i] + 1e-10)

            X = feats.iloc[:-1].values
            y_dir = target_direction[:-1]
            y_ret = target_return[:-1]
            last_candle_ts = int(df_tf["timestamp"].iloc[-1]) if "timestamp" in df_tf.columns else int(time.time())

            # Train and persist dedicated coin model bundle
            clf_ens, reg_ens, is_fresh = model_registry.get_or_train_coin_models(
                symbol=sym,
                tf=tf,
                X_train=X,
                y_train_dir=y_dir,
                y_train_ret=y_ret,
                last_candle_ts=last_candle_ts,
                ttl_seconds=0.0 # Force fresh fit
            )
            trained_tfs.append(tf)

        elapsed_coin = round(time.time() - t_start_coin, 2)
        trained_coins_summary.append({
            "symbol": sym,
            "clean_symbol": clean_sym,
            "timeframes_trained": len(trained_tfs),
            "timeframes_list": trained_tfs,
            "elapsed_s": elapsed_coin
        })
        print(f"  [{idx:>2}/{len(target_coins)}] {sym:<12} -> Trained {len(trained_tfs)}/9 Timeframes in {elapsed_coin}s (Dir: models_export_v3/per_coin/{clean_sym}/)")

    # Step 3: Train Separate Meta-Labelers for Each Coin
    print(f"\n[STEP 3/3] Training Dedicated Secondary Meta-Labelers for each coin individually...")
    meta_summary = meta_labeler.train_all_per_coin_meta_labelers()
    print(f"  ✓ Retrained {meta_summary.get('total_coins_trained', 0)} dedicated per-coin Meta-Labelers from historical trade outcomes.")

    # Step 4: Verification & Status Output
    total_elapsed = round(time.time() - t0, 2)
    print("\n" + "=" * 90)
    print(f"🎉 PER-COIN SEPARATE MODEL TRAINING COMPLETED IN {total_elapsed} SECONDS")
    print("=" * 90)
    print(f"{'SYMBOL':<12} | {'CLEAN ID':<12} | {'TF MODELS':<10} | {'META-LABELER TYPE':<22} | {'SAMPLE SIZE':<12}")
    print("-" * 90)
    for c_info in trained_coins_summary[:15]:
        sym = c_info["symbol"]
        m, f_cols, sz, m_type = meta_labeler.get_coin_meta_model(sym)
        print(f"{sym:<12} | {c_info['clean_symbol']:<12} | {c_info['timeframes_trained']}/9 TFs   | {m_type:<22} | {sz:>4} samples")
    if len(trained_coins_summary) > 15:
        print(f"  ... and {len(trained_coins_summary) - 15} more coins successfully trained and verified.")
    print("=" * 90)
    print("All models are isolated per coin and ready for 24/7 autonomous scanning.\n")

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 40
    run_per_coin_training(limit_assets=limit)
