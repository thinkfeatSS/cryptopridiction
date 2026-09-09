import os
import sys
import json
import time
import threading
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# UTF-8 Safe Console Output
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score

# Models and Data Paths
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODELS_DIR = os.path.join(WORKSPACE_ROOT, "models_export_v3")
os.makedirs(MODELS_DIR, exist_ok=True)

META_MODEL_PATH = os.path.join(MODELS_DIR, "signal_meta_classifier.joblib")
MODEL_STATUS_PATH = os.path.join(MODELS_DIR, "model_status.json")

# Retraining Mutex Lock & State
_retrain_lock = threading.Lock()
_retrain_state = {
    "is_training": False,
    "last_started_at": None,
    "last_completed_at": None,
    "last_error": None,
    "last_status": "IDLE",
    "retrain_count": 0
}


def extract_features_from_records(df: pd.DataFrame) -> pd.DataFrame:
    """Preprocesses and extracts quantitative meta-features from signal records."""
    data = []
    for _, row in df.iterrows():
        try:
            status_str = str(row.get('status', '')).upper()
            outcome_str = str(row.get('outcome_label', '')).upper()
            
            if "WON" in status_str or "WON" in outcome_str:
                target = 1
            elif "LOST" in status_str or "LOST" in outcome_str:
                target = 0
            else:
                continue # Skip pending or unverified
            
            conviction = float(row.get('conviction_pct', 70.0) or 70.0)
            exp_ret_raw = str(row.get('expected_return_pct', '0.0')).replace('%', '').replace('+', '').strip()
            exp_ret = float(exp_ret_raw) if exp_ret_raw not in ['', 'nan', 'None'] else 0.0
            
            rr_raw = str(row.get('risk_reward_ratio', '1:2.0')).split(':')[-1]
            try:
                rr_ratio = float(rr_raw)
            except Exception:
                rr_ratio = 2.0

            grade_str = str(row.get('quality_grade', ''))
            is_a_plus = 1.0 if "A+" in grade_str else 0.0
            
            horizon_str = str(row.get('horizon', '')).lower()
            is_scalp = 1.0 if "scalp" in horizon_str or "15m" in horizon_str else 0.0
            is_swing = 1.0 if "swing" in horizon_str or "1h" in horizon_str else 0.0
            is_macro = 1.0 if any(k in horizon_str for k in ["macro", "24h", "1d", "2d", "3d", "7d", "15d", "30d", "week", "month", "48h", "72h"]) else 0.0
            
            direction_str = str(row.get('direction', '')).upper()
            is_long = 1.0 if direction_str == "LONG" or "BULLISH" in direction_str else 0.0
            
            decision_str = str(row.get('decision', '')).upper()
            is_dip_buy = 1.0 if "DIP-BUY" in decision_str else 0.0
            is_rally_sell = 1.0 if "RALLY-SELL" in decision_str else 0.0
            is_bottom_reversal = 1.0 if "BOTTOM-REVERSAL" in decision_str else 0.0
            is_top_reversal = 1.0 if "TOP-REVERSAL" in decision_str else 0.0
            is_reversal = 1.0 if (is_bottom_reversal or is_top_reversal) else 0.0
            is_liq_sweep = 1.0 if "LIQUIDITY-SWEEP" in decision_str else 0.0
            is_squeeze = 1.0 if "SHORT SQUEEZE" in decision_str else 0.0
            is_paper_exec = 1.0 if "EXECUTED" in str(row.get('paper_trading_status', '')).upper() else 0.0
            
            rank_raw = str(row.get('rank', '#1')).replace('#', '').strip()
            try:
                rank = float(rank_raw)
            except Exception:
                rank = 1.0

            entry_p = float(row.get('entry_price', 1.0) or 1.0)
            tp1_p = float(row.get('tp1_price', 1.0) or 1.0)
            sl_p = float(row.get('sl_price', 1.0) or 1.0)
            
            if entry_p > 0 and sl_p > 0:
                tp_pct = abs(tp1_p - entry_p) / entry_p * 100.0
                sl_pct = abs(entry_p - sl_p) / entry_p * 100.0
            else:
                tp_pct = abs(exp_ret)
                sl_pct = abs(exp_ret) / max(1.0, rr_ratio)

            feat_dict = {
                'conviction_pct': conviction,
                'expected_return_pct': exp_ret,
                'risk_reward_ratio': rr_ratio,
                'is_a_plus': is_a_plus,
                'is_scalp': is_scalp,
                'is_swing': is_swing,
                'is_macro': is_macro,
                'is_long': is_long,
                'is_dip_buy': is_dip_buy,
                'is_rally_sell': is_rally_sell,
                'is_bottom_reversal': is_bottom_reversal,
                'is_top_reversal': is_top_reversal,
                'is_reversal': is_reversal,
                'is_liq_sweep': is_liq_sweep,
                'is_squeeze': is_squeeze,
                'is_paper_exec': is_paper_exec,
                'rank': rank,
                'tp_pct': tp_pct,
                'sl_pct': sl_pct,
                'tp_sl_ratio': tp_pct / max(0.01, sl_pct),
                'target': target
            }
            data.append(feat_dict)
        except Exception:
            continue
            
    return pd.DataFrame(data)


def load_all_resolved_signals() -> pd.DataFrame:
    """Aggregates all historical resolved signals from Database and CSV tracking files."""
    dfs = []
    
    # 1. Load from DB if available
    try:
        from app.database import SessionLocal
        from app.models.signal import SignalAudit
        db = SessionLocal()
        try:
            records = db.query(SignalAudit).all()
            if records:
                db_dicts = [r.to_dict() for r in records]
                df_db = pd.DataFrame(db_dicts)
                if len(df_db) > 0:
                    dfs.append(df_db)
        finally:
            db.close()
    except Exception as e:
        pass

    # 2. Load from CSV candidate sources
    csv_candidates = [
        os.path.join(WORKSPACE_ROOT, "user_pasted_signals.csv"),
        os.path.join(WORKSPACE_ROOT, "export_app_data", "trader_signals_tracker.csv"),
    ]
    for c in csv_candidates:
        if os.path.exists(c):
            try:
                d = pd.read_csv(c)
                if len(d) > 0:
                    dfs.append(d)
            except Exception:
                pass

    if not dfs:
        return pd.DataFrame()

    full_raw = pd.concat(dfs, ignore_index=True)
    if 'signal_id' in full_raw.columns:
        full_raw = full_raw.drop_duplicates(subset=['signal_id'], keep='last')
    return full_raw


def get_model_status() -> Dict[str, Any]:
    """Returns the current model metadata and training status."""
    info = {
        "model_path": META_MODEL_PATH,
        "is_model_present": os.path.exists(META_MODEL_PATH),
        "model_file_size_bytes": os.path.getsize(META_MODEL_PATH) if os.path.exists(META_MODEL_PATH) else 0,
        "retrain_state": _retrain_state,
        "model_metadata": None
    }
    
    if os.path.exists(MODEL_STATUS_PATH):
        try:
            with open(MODEL_STATUS_PATH, "r", encoding="utf-8") as f:
                info["model_metadata"] = json.load(f)
        except Exception:
            pass
    elif os.path.exists(META_MODEL_PATH):
        try:
            bundle = joblib.load(META_MODEL_PATH)
            info["model_metadata"] = {
                "trained_at_utc": bundle.get("trained_at_utc"),
                "sample_size": bundle.get("sample_size"),
                "baseline_win_rate": bundle.get("baseline_win_rate"),
                "auc_score": bundle.get("auc_score"),
                "feature_cols_count": len(bundle.get("feature_cols", []))
            }
        except Exception:
            pass
            
    return info


def run_retraining_pipeline(force: bool = False, min_new_samples: int = 5) -> Dict[str, Any]:
    """
    Synchronous model training execution with validation checks and atomic checkpointing.
    """
    global _retrain_state
    
    if not _retrain_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "Retraining is already in progress in another thread.",
            "status": "RUNNING"
        }

    now_utc = datetime.now(timezone.utc).isoformat()
    _retrain_state["is_training"] = True
    _retrain_state["last_started_at"] = now_utc
    _retrain_state["last_status"] = "TRAINING"
    _retrain_state["last_error"] = None

    try:
        full_raw = load_all_resolved_signals()
        if len(full_raw) == 0:
            raise ValueError("No historical signals found across database and CSV sources.")

        feat_df = extract_features_from_records(full_raw)
        total_resolved = len(feat_df)
        
        if total_resolved < 15:
            raise ValueError(f"Insufficient resolved trade samples ({total_resolved}) to train statistical ML model (minimum 15 required).")

        # Check threshold compared to last training run
        last_status = {}
        if os.path.exists(MODEL_STATUS_PATH):
            try:
                with open(MODEL_STATUS_PATH, "r", encoding="utf-8") as f:
                    last_status = json.load(f)
            except Exception:
                pass
        
        last_sample_size = last_status.get("sample_size", 0)
        new_samples = total_resolved - last_sample_size
        
        if not force and new_samples < min_new_samples and last_sample_size > 0:
            _retrain_state["is_training"] = False
            _retrain_state["last_status"] = "SKIPPED_NO_DRIFT"
            return {
                "success": True,
                "message": f"Retraining skipped: only {new_samples} new resolved samples since last run (threshold: {min_new_samples}).",
                "sample_size": total_resolved,
                "new_samples": new_samples,
                "status": "UP_TO_DATE"
            }

        feature_cols = [c for c in feat_df.columns if c != 'target']
        X = feat_df[feature_cols]
        y = feat_df['target']

        # Model Architecture: LightGBM with HistGradientBoosting Fallback
        if HAS_LIGHTGBM:
            base_clf = lgb.LGBMClassifier(
                n_estimators=120,
                max_depth=3,
                num_leaves=8,
                learning_rate=0.04,
                subsample=0.85,
                colsample_bytree=0.80,
                min_child_samples=5,
                random_state=42,
                verbose=-1
            )
        else:
            base_clf = HistGradientBoostingClassifier(
                max_iter=120,
                max_depth=3,
                learning_rate=0.04,
                min_samples_leaf=5,
                random_state=42
            )

        calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3)
        calibrated_clf.fit(X, y)

        preds = calibrated_clf.predict(X)
        probs = calibrated_clf.predict_proba(X)[:, 1]
        acc = float(accuracy_score(y, preds))
        try:
            auc = float(roc_auc_score(y, probs))
        except Exception:
            auc = 0.50
        prec = float(precision_score(y, preds, zero_division=0))

        # Model Quality Gate
        if auc < 0.65:
            print(f"[MODEL RETRAIN ⚠️] Warning: Retrained candidate model AUC ({auc:.3f}) below 0.65 threshold. Preserving existing model.")
            raise ValueError(f"Trained model did not pass quality validation gate (AUC {auc:.3f} < 0.65).")

        # Save Atomic Joblib Model Bundle
        bundle = {
            'model': calibrated_clf,
            'feature_cols': feature_cols,
            'trained_at_utc': datetime.now(timezone.utc).isoformat(),
            'sample_size': total_resolved,
            'baseline_win_rate': float(y.mean()),
            'accuracy': acc,
            'auc_score': auc,
            'precision': prec
        }
        
        tmp_model_path = META_MODEL_PATH + ".tmp"
        joblib.dump(bundle, tmp_model_path)
        os.replace(tmp_model_path, META_MODEL_PATH)

        # Save Model Status JSON
        status_payload = {
            "model_path": META_MODEL_PATH,
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "sample_size": total_resolved,
            "wins_count": int(sum(y == 1)),
            "losses_count": int(sum(y == 0)),
            "baseline_win_rate": round(float(y.mean()) * 100.0, 1),
            "accuracy_pct": round(acc * 100.0, 1),
            "auc_score": round(auc, 4),
            "precision_pct": round(prec * 100.0, 1),
            "feature_cols": feature_cols,
            "has_lightgbm": HAS_LIGHTGBM
        }
        with open(MODEL_STATUS_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(status_payload, f, indent=2)
        os.replace(MODEL_STATUS_PATH + ".tmp", MODEL_STATUS_PATH)

        _retrain_state["is_training"] = False
        _retrain_state["last_completed_at"] = datetime.now(timezone.utc).isoformat()
        _retrain_state["last_status"] = "SUCCESS"
        _retrain_state["retrain_count"] += 1

        print(f"[MODEL RETRAIN] Retraining completed successfully! Samples: {total_resolved}, Acc: {acc*100:.1f}%, AUC: {auc:.3f}")
        return {
            "success": True,
            "message": "Model retrained and hot-reloaded successfully.",
            "metrics": status_payload,
            "status": "COMPLETED"
        }

    except Exception as e:
        _retrain_state["is_training"] = False
        _retrain_state["last_error"] = str(e)
        _retrain_state["last_status"] = "FAILED"
        print(f"[MODEL RETRAIN ERROR] Error during retraining: {e}")
        return {
            "success": False,
            "message": f"Retraining failed: {e}",
            "status": "FAILED"
        }
    finally:
        _retrain_lock.release()


def check_and_trigger_async(force: bool = False, min_new_samples: int = 5):
    """Fires retraining asynchronously in background thread without blocking."""
    t = threading.Thread(
        target=run_retraining_pipeline,
        kwargs={"force": force, "min_new_samples": min_new_samples},
        daemon=True
    )
    t.start()
    return t


if __name__ == "__main__":
    res = run_retraining_pipeline(force=True)
    print(json.dumps(res, indent=2))
