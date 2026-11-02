"""
QUANT EDGE V16: Institutional ML Validation Protocol & Walk-Forward Audit
Evaluates:
- 5 Classifiers individually + Ensemble Voting
- Uncalibrated vs Platt (Sigmoid) vs Isotonic Calibration
- Brier Score, Brier Skill Score, Log Loss, ECE (10 bins), ROC-AUC, Precision, Recall
- Prediction Error Correlation Matrix
- 5 Regressors individually + Modal Consensus Clustering (MAE, RMSE, Directional Confluence)
- Candidate Model Promotion Gate verification
"""

import sys
import os
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

from sklearn.metrics import (
    brier_score_loss,
    log_loss,
    roc_auc_score,
    precision_score,
    recall_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error
)
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from catboost import CatBoostClassifier, CatBoostRegressor
from xgboost import XGBClassifier, XGBRegressor
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    RandomForestClassifier,
    RandomForestRegressor
)

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.services.model_retrainer import extract_features_from_records, load_all_resolved_signals
from app.engine.signals.ensemble_classifier import FiveModelDirectionClassifier
from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor

def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Computes Expected Calibration Error (ECE) across uniform probability bins."""
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

def run_ml_validation_suite(csv_path: str = "freeze_archive_trader_signals_tracker.csv"):
    print("=" * 80)
    print("QUANT EDGE V16: INSTITUTIONAL ML VALIDATION & CALIBRATION PROTOCOL")
    print("=" * 80)

    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    raw_df = pd.read_csv(csv_path)
    print(f"Loaded {len(raw_df)} signals from {csv_path}")

    # Chronological sort
    if "date_utc" in raw_df.columns:
        time_c = raw_df["time_utc"].fillna("00:00:00") if "time_utc" in raw_df.columns else "00:00:00"
        raw_df["dt_sort"] = raw_df["date_utc"].astype(str) + " " + time_c.astype(str)
        raw_df = raw_df.sort_values("dt_sort").reset_index(drop=True)

    feat_df = extract_features_from_records(raw_df)
    print(f"Extracted {len(feat_df)} resolved trade records with target labels.")
    n_total = len(feat_df)
    if n_total < 40:
        print("Sample size too small for walk-forward validation.")
        return

    # Chronological Walk-Forward Split:
    # 50% Train, 25% Out-of-sample Validation / Calibration, 25% Untouched Final Holdout
    split1 = int(n_total * 0.50)
    split2 = int(n_total * 0.75)

    train_df = feat_df.iloc[:split1].copy()
    val_df = feat_df.iloc[split1:split2].copy()
    holdout_df = feat_df.iloc[split2:].copy()

    feature_cols = [c for c in feat_df.columns if c != 'target']
    X_train, y_train = train_df[feature_cols].values, train_df['target'].values
    X_val, y_val = val_df[feature_cols].values, val_df['target'].values
    X_holdout, y_holdout = holdout_df[feature_cols].values, holdout_df['target'].values

    train_base_prob = float(np.mean(y_train))
    holdout_base_prob = float(np.mean(y_holdout))
    print(f"Dataset Partitioning: Train={len(train_df)} (Base WR={train_base_prob*100:.1f}%), "
          f"Val={len(val_df)}, Holdout={len(holdout_df)} (Base WR={holdout_base_prob*100:.1f}%)")

    # 1. EVALUATION OF THE 5 CLASSIFIERS ON FINAL HOLDOUT
    clf_instances = {
        "CatBoost": CatBoostClassifier(iterations=100, depth=3, learning_rate=0.04, verbose=0, random_seed=42),
        "XGBoost": XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.04, eval_metric="logloss", random_state=42),
        "HistGradientBoosting": HistGradientBoostingClassifier(max_iter=100, max_depth=3, learning_rate=0.04, random_state=42),
        "ExtraTrees": ExtraTreesClassifier(n_estimators=100, max_depth=4, random_state=42),
        "RandomForest": RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
    }

    results = {}
    prob_matrix = {}
    preds_binary = {}

    # Naive baseline Brier score: predicting the constant prior (training mean)
    brier_baseline = float(brier_score_loss(y_holdout, np.full(len(y_holdout), train_base_prob)))
    ll_baseline = float(log_loss(y_holdout, np.full(len(y_holdout), train_base_prob)))

    print("\n[PHASE 4.1] Individual Classifiers Evaluated on Chronological Holdout:")
    for name, model in clf_instances.items():
        model.fit(X_train, y_train)
        probs = model.predict_proba(X_holdout)[:, 1]
        preds = (probs >= 0.50).astype(int)

        prob_matrix[name] = probs
        preds_binary[name] = preds

        bs = float(brier_score_loss(y_holdout, probs))
        bss = float(1.0 - (bs / max(1e-6, brier_baseline))) # Brier Skill Score
        ll = float(log_loss(y_holdout, probs))
        ece = compute_ece(y_holdout, probs, n_bins=10)
        try:
            auc = float(roc_auc_score(y_holdout, probs))
        except Exception:
            auc = 0.50
        prec = float(precision_score(y_holdout, preds, zero_division=0))
        rec = float(recall_score(y_holdout, preds, zero_division=0))
        f1 = float(f1_score(y_holdout, preds, zero_division=0))

        results[name] = {
            "brier_score": round(bs, 4),
            "brier_skill_score": round(bss, 4),
            "log_loss": round(ll, 4),
            "ece_10_bins": round(ece, 4),
            "roc_auc": round(auc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4)
        }
        print(f"  * {name:20s}: AUC={auc:.3f}, Brier={bs:.4f}, BSS={bss:+.4f}, LogLoss={ll:.4f}, ECE={ece:.4f}, Prec={prec:.3f}, Rec={rec:.3f}")

    # 2. ENSEMBLE CONSENSUS VOTING
    ensemble_probs = np.mean(list(prob_matrix.values()), axis=0)
    ensemble_votes = (np.sum(list(preds_binary.values()), axis=0) >= 3).astype(int)

    ens_bs = float(brier_score_loss(y_holdout, ensemble_probs))
    ens_bss = float(1.0 - (ens_bs / max(1e-6, brier_baseline)))
    ens_ll = float(log_loss(y_holdout, ensemble_probs))
    ens_ece = compute_ece(y_holdout, ensemble_probs, n_bins=10)
    try:
        ens_auc = float(roc_auc_score(y_holdout, ensemble_probs))
    except Exception:
        ens_auc = 0.50
    ens_prec = float(precision_score(y_holdout, ensemble_votes, zero_division=0))
    ens_rec = float(recall_score(y_holdout, ensemble_votes, zero_division=0))
    ens_f1 = float(f1_score(y_holdout, ensemble_votes, zero_division=0))

    results["5-Model Ensemble Consensus"] = {
        "brier_score": round(ens_bs, 4),
        "brier_skill_score": round(ens_bss, 4),
        "log_loss": round(ens_ll, 4),
        "ece_10_bins": round(ens_ece, 4),
        "roc_auc": round(ens_auc, 4),
        "precision": round(ens_prec, 4),
        "recall": round(ens_rec, 4),
        "f1": round(ens_f1, 4)
    }
    print(f"\n  * 5-Model Ensemble    : AUC={ens_auc:.3f}, Brier={ens_bs:.4f}, BSS={ens_bss:+.4f}, LogLoss={ens_ll:.4f}, ECE={ens_ece:.4f}, Prec={ens_prec:.3f}, Rec={ens_rec:.3f}")

    # 3. PROBABILITY CALIBRATION METHODS COMPARISON (Out-of-sample on Val, tested on Holdout)
    print("\n[PHASE 4.2] Out-of-Sample Calibration Testing (Uncalibrated vs Platt vs Isotonic):")
    calib_comparison = {}
    base_estimator = HistGradientBoostingClassifier(max_iter=100, max_depth=3, learning_rate=0.04, random_state=42)
    base_estimator.fit(X_train, y_train)

    from sklearn.linear_model import LogisticRegression
    from sklearn.isotonic import IsotonicRegression

    val_probs = base_estimator.predict_proba(X_val)[:, 1]
    holdout_probs = base_estimator.predict_proba(X_holdout)[:, 1]

    # A: Raw Uncalibrated
    raw_ece = compute_ece(y_holdout, holdout_probs, 10)
    raw_bs = float(brier_score_loss(y_holdout, holdout_probs))
    calib_comparison["Uncalibrated"] = {"brier": round(raw_bs, 4), "ece": round(raw_ece, 4)}

    # B: Platt Scaling (Sigmoid fitted on out-of-sample Val)
    platt = LogisticRegression(C=1.0, solver='lbfgs')
    platt.fit(val_probs.reshape(-1, 1), y_val)
    platt_probs = platt.predict_proba(holdout_probs.reshape(-1, 1))[:, 1]
    platt_ece = compute_ece(y_holdout, platt_probs, 10)
    platt_bs = float(brier_score_loss(y_holdout, platt_probs))
    calib_comparison["Platt (Sigmoid)"] = {"brier": round(platt_bs, 4), "ece": round(platt_ece, 4)}

    # C: Isotonic Regression (fitted on out-of-sample Val)
    iso = IsotonicRegression(out_of_bounds='clip', y_min=0.01, y_max=0.99)
    iso.fit(val_probs, y_val)
    iso_probs = iso.predict(holdout_probs)
    iso_ece = compute_ece(y_holdout, iso_probs, 10)
    iso_bs = float(brier_score_loss(y_holdout, iso_probs))
    calib_comparison["Isotonic Regression"] = {"brier": round(iso_bs, 4), "ece": round(iso_ece, 4)}

    for method, metrics in calib_comparison.items():
        print(f"  * {method:22s}: Brier Score={metrics['brier']:.4f}, ECE (10 bins)={metrics['ece']:.4f}")

    # 4. PREDICTION ERROR CORRELATION MATRIX
    error_matrix = {}
    for name, probs in prob_matrix.items():
        errors = y_holdout - probs
        error_matrix[name] = errors
    error_df = pd.DataFrame(error_matrix)
    corr_matrix = error_df.corr().round(3)
    print("\n[PHASE 4.3] Model Error Correlation Matrix (Ensemble Diversity):")
    print(corr_matrix.to_string())

    # 5. REGRESSOR EVALUATION (Target: Target Return)
    print("\n[PHASE 4.4] Regressors Evaluation on Chronological Holdout:")
    # Synthetic target returns based on tp_pct and sl_pct
    y_train_ret = np.where(y_train == 1, train_df['tp_pct'].values / 100.0, -train_df['sl_pct'].values / 100.0)
    y_holdout_ret = np.where(y_holdout == 1, holdout_df['tp_pct'].values / 100.0, -holdout_df['sl_pct'].values / 100.0)

    reg_instances = {
        "CatBoost Regressor": CatBoostRegressor(iterations=100, depth=3, learning_rate=0.04, verbose=0, random_seed=42),
        "XGBoost Regressor": XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.04, random_state=42),
        "HistGradientBoosting": HistGradientBoostingRegressor(max_iter=100, max_depth=3, learning_rate=0.04, random_state=42),
        "ExtraTrees Regressor": ExtraTreesRegressor(n_estimators=100, max_depth=4, random_state=42),
        "RandomForest Regressor": RandomForestRegressor(n_estimators=100, max_depth=4, random_state=42)
    }

    reg_results = {}
    reg_preds_matrix = {}
    for name, r_model in reg_instances.items():
        r_model.fit(X_train, y_train_ret)
        preds = r_model.predict(X_holdout)
        reg_preds_matrix[name] = preds

        mae = float(mean_absolute_error(y_holdout_ret, preds))
        rmse = float(np.sqrt(mean_squared_error(y_holdout_ret, preds)))
        dir_acc = float(np.mean((preds > 0) == (y_holdout_ret > 0))) * 100.0

        reg_results[name] = {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "dir_acc_pct": round(dir_acc, 2)
        }
        print(f"  * {name:22s}: MAE={mae:.4f}, RMSE={rmse:.4f}, Directional Confluence={dir_acc:.1f}%")

    # Consensus Regression (Median of regressors)
    ens_reg_preds = np.median(list(reg_preds_matrix.values()), axis=0)
    ens_mae = float(mean_absolute_error(y_holdout_ret, ens_reg_preds))
    ens_rmse = float(np.sqrt(mean_squared_error(y_holdout_ret, ens_reg_preds)))
    ens_dir_acc = float(np.mean((ens_reg_preds > 0) == (y_holdout_ret > 0))) * 100.0
    reg_results["Modal Consensus Regressor"] = {
        "mae": round(ens_mae, 4),
        "rmse": round(ens_rmse, 4),
        "dir_acc_pct": round(ens_dir_acc, 2)
    }
    print(f"  * Modal Consensus Regressor : MAE={ens_mae:.4f}, RMSE={ens_rmse:.4f}, Directional Confluence={ens_dir_acc:.1f}%")

    # 6. CANDIDATE MODEL PROMOTION GATE SIMULATION
    print("\n[PHASE 4.5] Candidate-Model Promotion Gate Audit:")
    incumbent_auc = 0.65
    candidate_auc = ens_auc
    candidate_ece = ens_ece

    passed_auc_gate = (candidate_auc >= incumbent_auc)
    passed_ece_gate = (candidate_ece <= 0.08)

    gate_status = "PROMOTED" if (passed_auc_gate and passed_ece_gate) else "REJECTED (INCUMBENT RETAINED)"
    print(f"  - Incumbent Baseline AUC Threshold: {incumbent_auc:.3f}")
    print(f"  - Candidate Model AUC on Holdout : {candidate_auc:.3f} -> {'PASS' if passed_auc_gate else 'FAIL'}")
    print(f"  - Candidate Model ECE on Holdout : {candidate_ece:.4f} -> {'PASS' if passed_ece_gate else 'FAIL'}")
    print(f"  - Formal Gate Verdict            : {gate_status}")

    return {
        "sample_counts": {"total": n_total, "train": len(train_df), "val": len(val_df), "holdout": len(holdout_df)},
        "baseline_metrics": {"brier_baseline": brier_baseline, "log_loss_baseline": ll_baseline},
        "classifiers": results,
        "calibration": calib_comparison,
        "correlation": corr_matrix.to_dict(),
        "regressors": reg_results,
        "promotion_gate": {
            "incumbent_auc": incumbent_auc,
            "candidate_auc": candidate_auc,
            "candidate_ece": candidate_ece,
            "passed_auc_gate": passed_auc_gate,
            "passed_ece_gate": passed_ece_gate,
            "gate_status": gate_status
        }
    }

if __name__ == "__main__":
    run_ml_validation_suite()
