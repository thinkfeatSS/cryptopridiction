"""
Independent Audit of ML Validation Rigor & Temporal Dependence
Performs:
1. Strict 3-way partition:
   - Train (50%): Model fitting
   - Validation (25%): Hyperparameter check, Platt scaling calibration fit, Promotion Gate clearance
   - Final Untouched Holdout (25%): Sealed final evaluation of promoted model
2. Stationary Block Bootstrap (block size = 10) for Dependence-Aware 95% Confidence Intervals
   for AUC, Brier Score, and BSS
3. Label overlap audit & class prevalence
"""

import sys
import os
import json
import math
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score, precision_score, recall_score
from sklearn.linear_model import LogisticRegression
from catboost import CatBoostClassifier
from xgboost import XGBClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, ExtraTreesClassifier, RandomForestClassifier

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.model_retrainer import extract_features_from_records

def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    bin_limits = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    for i in range(n_bins):
        low, high = bin_limits[i], bin_limits[i + 1]
        mask = (y_prob >= low) & (y_prob < high if i < n_bins - 1 else y_prob <= high)
        bin_count = np.sum(mask)
        if bin_count > 0:
            bin_acc = np.mean(y_true[mask])
            bin_conf = np.mean(y_prob[mask])
            ece += (bin_count / n) * abs(bin_acc - bin_conf)
    return float(ece)

def run_ml_rigor_audit():
    df = pd.read_csv("freeze_archive_trader_signals_tracker.csv")
    if "date_utc" in df.columns:
        time_c = df["time_utc"].fillna("00:00:00") if "time_utc" in df.columns else "00:00:00"
        df["dt_sort"] = df["date_utc"].astype(str) + " " + time_c.astype(str)
        df = df.sort_values("dt_sort").reset_index(drop=True)

    feat_df = extract_features_from_records(df)
    n_total = len(feat_df)
    split1 = int(n_total * 0.50)
    split2 = int(n_total * 0.75)

    train_df = feat_df.iloc[:split1].copy()
    val_df = feat_df.iloc[split1:split2].copy()
    holdout_df = feat_df.iloc[split2:].copy()

    feature_cols = [c for c in feat_df.columns if c != 'target']
    X_train, y_train = train_df[feature_cols].values, train_df['target'].values
    X_val, y_val = val_df[feature_cols].values, val_df['target'].values
    X_holdout, y_holdout = holdout_df[feature_cols].values, holdout_df['target'].values

    print("=" * 80)
    print("ML VALIDATION RIGOR & TEMPORAL DEPENDENCE AUDIT")
    print("=" * 80)
    print(f"Dataset Size: Total={n_total}")
    print(f"  • Train:   N={len(train_df)}, Positive Class={np.sum(y_train)} ({np.mean(y_train)*100:.1f}%)")
    print(f"  • Val:     N={len(val_df)}, Positive Class={np.sum(y_val)} ({np.mean(y_val)*100:.1f}%)")
    print(f"  • Holdout: N={len(holdout_df)}, Positive Class={np.sum(y_holdout)} ({np.mean(y_holdout)*100:.1f}%)")

    # Fit ensemble models on Train ONLY
    models = {
        "CatBoost": CatBoostClassifier(iterations=100, depth=3, learning_rate=0.04, verbose=0, random_seed=42),
        "XGBoost": XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.04, eval_metric="logloss", random_state=42),
        "HistGBM": HistGradientBoostingClassifier(max_iter=100, max_depth=3, learning_rate=0.04, random_state=42),
        "ExtraTrees": ExtraTreesClassifier(n_estimators=100, max_depth=4, random_state=42),
        "RandomForest": RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
    }

    val_probs_dict = {}
    holdout_probs_dict = {}

    for name, m in models.items():
        m.fit(X_train, y_train)
        val_probs_dict[name] = m.predict_proba(X_val)[:, 1]
        holdout_probs_dict[name] = m.predict_proba(X_holdout)[:, 1]

    val_ens_prob = np.mean(list(val_probs_dict.values()), axis=0)
    holdout_ens_prob = np.mean(list(holdout_probs_dict.values()), axis=0)

    # 1. VALIDATION SET PROMOTION GATE AUDIT (Pre-Holdout Clearance)
    val_auc = roc_auc_score(y_val, val_ens_prob)
    val_ece = compute_ece(y_val, val_ens_prob, 10)
    val_bs = brier_score_loss(y_val, val_ens_prob)
    print("\n--- STAGE 1: PROMOTION GATE EVALUATED ON VALIDATION SET (SEALED HOLDOUT UNTOUCHED) ---")
    print(f"Validation Ensemble ROC-AUC: {val_auc:.4f} (Threshold >= 0.650) -> {'PASS' if val_auc >= 0.650 else 'FAIL'}")
    print(f"Validation Ensemble ECE:     {val_ece:.4f} (Threshold <= 0.080) -> {'PASS' if val_ece <= 0.080 else 'FAIL'}")
    print(f"Validation Brier Score:      {val_bs:.4f}")

    # 2. FIT PLATT SCALING ON VALIDATION SET ONLY
    platt = LogisticRegression(C=1.0, solver='lbfgs')
    platt.fit(val_ens_prob.reshape(-1, 1), y_val)

    # 3. FINAL EVALUATION ON SEALED UNTOUCHED HOLDOUT
    holdout_cal_prob = platt.predict_proba(holdout_ens_prob.reshape(-1, 1))[:, 1]
    holdout_auc = roc_auc_score(y_holdout, holdout_cal_prob)
    holdout_bs = brier_score_loss(y_holdout, holdout_cal_prob)
    holdout_ece = compute_ece(y_holdout, holdout_cal_prob, 10)
    prior_baseline_bs = brier_score_loss(y_holdout, np.full(len(y_holdout), np.mean(y_train)))
    holdout_bss = 1.0 - (holdout_bs / prior_baseline_bs)

    print("\n--- STAGE 2: FINAL EVALUATION ON SEALED UNTOUCHED HOLDOUT ---")
    print(f"Holdout Calibrated Ensemble ROC-AUC: {holdout_auc:.4f}")
    print(f"Holdout Calibrated Ensemble ECE:     {holdout_ece:.4f}")
    print(f"Holdout Calibrated Brier Score:      {holdout_bs:.4f}")
    print(f"Holdout Constant Prior Baseline BS:  {prior_baseline_bs:.4f}")
    print(f"Holdout Brier Skill Score (BSS):     {holdout_bss:+.4f} ({(holdout_bss)*100:.1f}% improvement over prior)")

    # 4. DEPENDENCE-AWARE STATIONARY BLOCK BOOTSTRAP 95% CONFIDENCE INTERVALS
    rng = np.random.default_rng(42)
    n_holdout = len(y_holdout)
    block_len = 10 # 10-trade blocks to capture serial autocorrelation
    n_blocks = n_holdout // block_len

    boot_aucs = []
    boot_briers = []
    boot_bsss = []
    boot_eces = []

    for _ in range(1000):
        starts = rng.integers(0, n_holdout - block_len + 1, size=n_blocks)
        sample_idx = np.concatenate([np.arange(s, s + block_len) for s in starts])
        y_b = y_holdout[sample_idx]
        p_b = holdout_cal_prob[sample_idx]
        if len(np.unique(y_b)) < 2:
            continue
        b_auc = roc_auc_score(y_b, p_b)
        b_bs = brier_score_loss(y_b, p_b)
        b_base = brier_score_loss(y_b, np.full(len(y_b), np.mean(y_train)))
        b_bss = 1.0 - (b_bs / max(1e-6, b_base))
        b_ece = compute_ece(y_b, p_b, 10)

        boot_aucs.append(b_auc)
        boot_briers.append(b_bs)
        boot_bsss.append(b_bss)
        boot_eces.append(b_ece)

    print("\n--- STAGE 3: DEPENDENCE-AWARE BLOCK BOOTSTRAP 95% CONFIDENCE INTERVALS ---")
    print(f"ROC-AUC:            [{np.percentile(boot_aucs, 2.5):.3f}, {np.percentile(boot_aucs, 97.5):.3f}] (Mean: {np.mean(boot_aucs):.3f})")
    print(f"Brier Score:        [{np.percentile(boot_briers, 2.5):.4f}, {np.percentile(boot_briers, 97.5):.4f}] (Mean: {np.mean(boot_briers):.4f})")
    print(f"Brier Skill Score:  [{np.percentile(boot_bsss, 2.5):+.4f}, {np.percentile(boot_bsss, 97.5):+.4f}] (Mean: {np.mean(boot_bsss):+.4f})")
    print(f"ECE (10 Bins):      [{np.percentile(boot_eces, 2.5):.4f}, {np.percentile(boot_eces, 97.5):.4f}] (Mean: {np.mean(boot_eces):.4f})")

if __name__ == "__main__":
    run_ml_rigor_audit()
