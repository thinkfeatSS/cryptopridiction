import os
import sys

# Critical: Prevent OpenMP / BLAS threading deadlocks
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import json
import time
import threading
import warnings
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Suppress serialization & version warnings from pre-trained sklearn / xgboost bundles
try:
    from sklearn.exceptions import InconsistentVersionWarning
    warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
except ImportError:
    pass
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*InconsistentVersionWarning.*")
warnings.filterwarnings("ignore", message=".*Trying to unpickle estimator.*")
warnings.filterwarnings("ignore", message=".*If you are loading a serialized model.*")

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


class SingleClassPriorModel:
    """Laplace-smoothed probability model for per-coin cold starts where only one class has resolved so far."""
    def __init__(self, target_class: int, sample_size: int):
        self.target_class = int(target_class)
        self.sample_size = int(sample_size)
        if self.target_class == 1:
            self.prob = (sample_size + 1.0) / (sample_size + 2.0)
        else:
            self.prob = 1.0 / (sample_size + 2.0)
            
    def predict_proba(self, X):
        p1 = float(self.prob)
        p0 = 1.0 - p1
        n = len(X)
        return np.array([[p0, p1]] * n)

def extract_features_from_records(df: pd.DataFrame) -> pd.DataFrame:
    """Preprocesses and extracts quantitative meta-features from signal records without lookahead bias."""
    data = []
    for _, row in df.iterrows():
        try:
            # 1. Clean Pure Target Label (Marcos López de Prado Triple-Barrier Meta-Labeling Framework):
            # Target 1 = Genuine TP Hit (WON_TP1, WON_TP2, WON_TP3, TP1_LOCKED, TP2_LOCKED, TP3_RUNNER, or MFE >= TP1 hurdle without stop out).
            # Target 0 = Failed to reach TP1 before expiry or stop-out (LOST_SL, LOST_EXP, WON_EXP_PROFIT, EXPIRED_PROFIT, TIER0_BE, BREAKEVEN_EXP, STAGNATION).
            status_str = str(row.get('status', '')).upper()
            outcome_str = str(row.get('outcome_label', '')).upper()
            combined_st = f"{status_str} {outcome_str}"
            
            if any(k in combined_st for k in ['PENDING', 'OPEN', 'ACTIVE', 'WAITING']):
                continue # Skip pending or unverified
                
            entry_p = float(row.get('entry_price', 0.0) or 0.0)
            tp1_p = float(row.get('tp1_price', 0.0) or 0.0)
            mfe_val = float(row.get('max_potential_gain_pct', 0.0) or 0.0)
            tp_pct = abs(tp1_p - entry_p) / entry_p * 100.0 if entry_p > 0 and tp1_p > 0 else 1.5

            # Strict Triple-Barrier Invalidation: Stop barrier crossing FIRST cannot be converted to a win by subsequent MFE!
            is_sl_hit = any(k in combined_st for k in ['LOST_SL', 'SL_HIT', 'STOP_LOSS', 'LOST_STOP', 'STOPPED', 'STOP_HIT', 'STOP_LOSS_HIT'])
            is_tp_hit = any(k in combined_st for k in ['WON_TP', 'TP1_LOCKED', 'TP2_LOCKED', 'TP3_RUNNER', 'TP1 HIT', 'TP2 HIT', 'TP3 HIT'])

            if is_sl_hit:
                target = 0
            elif is_tp_hit:
                target = 1
            elif mfe_val >= tp_pct and mfe_val >= 0.5:
                # Intra-trade MFE reached or exceeded TP1 hurdle before expiry without stopping out
                target = 1
            else:
                target = 0
            
            conviction = float(row.get('conviction_pct', 70.0) or 70.0)
            exp_ret_raw = str(row.get('expected_return_pct', '0.0')).replace('%', '').replace('+', '').strip()
            exp_ret = abs(float(exp_ret_raw)) if exp_ret_raw not in ['', 'nan', 'None'] else 0.0

            grade_str = str(row.get('quality_grade', ''))
            is_a_plus = 1.0 if "A+" in grade_str else 0.0
            
            # Horizon encoding aligned with institutional market structure (15M=Scalp, 1H/4H=Swing/Intraday, 24H+=Macro)
            horizon_str = str(row.get('horizon', '')).lower()
            is_scalp = 1.0 if any(k in horizon_str for k in ["scalp", "5m", "15m", "30m"]) else 0.0
            is_swing = 1.0 if any(k in horizon_str for k in ["swing", "intraday", "1h", "4h", "12h"]) else 0.0
            is_macro = 1.0 if any(k in horizon_str for k in ["macro", "24h", "1d", "2d", "3d", "4d", "7d", "15d", "30d", "week", "month", "48h", "72h"]) else 0.0
            
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
            is_order_block = 1.0 if "ORDER-BLOCK" in decision_str else 0.0
            is_breaker_block = 1.0 if "BREAKER-BLOCK" in decision_str else 0.0
            is_blowoff_top = 1.0 if "BLOW-OFF TOP" in decision_str else 0.0
            is_hype_surge = 1.0 if "HYPE PUMP" in decision_str else 0.0
            is_paper_exec = 1.0 if any(k in str(row.get('paper_trading_status', '')).upper() for k in ["EXECUTED", "ACTIVE"]) else 0.0
            
            rank_raw = str(row.get('rank', '#1')).replace('#', '').strip()
            try:
                rank = float(rank_raw)
            except Exception:
                rank = 1.0

            entry_p = float(row.get('entry_price', 1.0) or 1.0)
            tp1_p = float(row.get('tp1_price', 1.0) or 1.0)
            # Use un-ratcheted original stop loss to eliminate post-trade lookahead bias
            sl_raw = row.get('sl_original')
            if sl_raw is None or pd.isna(sl_raw) or float(sl_raw) <= 0:
                sl_raw = row.get('initial_sl_price') or row.get('sl_price', 1.0)
            sl_p = float(sl_raw or 1.0)
            
            if entry_p > 0 and sl_p > 0 and tp1_p > 0:
                tp_pct = abs(tp1_p - entry_p) / entry_p * 100.0
                sl_pct = abs(entry_p - sl_p) / entry_p * 100.0
            else:
                tp_pct = max(0.5, abs(exp_ret))
                sl_pct = max(0.3, abs(exp_ret) / 2.0)

            # Enforce valid economic minimum barrier distances
            if sl_pct < 0.20:
                sl_pct = max(0.20, abs(exp_ret) / 2.0 if abs(exp_ret) > 0 else 0.50)
            tp_pct = max(0.30, tp_pct)

            clean_rr = float(np.clip(round(tp_pct / max(0.05, sl_pct), 2), 0.1, 50.0))

            from app.engine.config import MEME_AND_SHITCOIN_BASES
            sym_str = str(row.get('symbol', '')).upper()
            clean_base_sym = sym_str.split("/")[0].split(":")[0].replace("1000", "").strip()
            is_meme = 1.0 if (clean_base_sym in MEME_AND_SHITCOIN_BASES or any(m in clean_base_sym for m in ["SHIB", "PEPE", "BONK", "DOGE", "FLOKI", "MEME", "WIF", "BOME", "GRAM"])) else 0.0

            feat_dict = {
                'conviction_pct': conviction,
                'expected_return_pct': exp_ret,
                'risk_reward_ratio': clean_rr,
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
                'is_order_block': is_order_block,
                'is_breaker_block': is_breaker_block,
                'is_blowoff_top': is_blowoff_top,
                'is_hype_surge': is_hype_surge,
                'is_paper_exec': is_paper_exec,
                'is_meme': is_meme,
                'rank': rank,
                'tp_pct': round(tp_pct, 2),
                'sl_pct': round(sl_pct, 2),
                'tp_sl_ratio': clean_rr,
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
        os.path.join(WORKSPACE_ROOT, "export_app_data", "live_container_trader_signals_tracker.csv"),
        os.path.join(WORKSPACE_ROOT, "export_app_data", "historical_meta_training_signals.csv"),
        os.path.join(WORKSPACE_ROOT, "latest_signals_from_container.csv"),
        os.path.join(WORKSPACE_ROOT, "latest_vps_signals.csv"),
        os.path.join(WORKSPACE_ROOT, "user_pasted_signals.csv"),
        os.path.join(WORKSPACE_ROOT, "vps_downloaded_signals.csv"),
        os.path.join(WORKSPACE_ROOT, "downloaded_signals.csv"),
        os.path.join(WORKSPACE_ROOT, "export_app_data", "trader_signals_tracker.csv"),
        os.path.join(WORKSPACE_ROOT, "trader_signals_tracker.csv"),
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
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
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


def run_retraining_pipeline(force: bool = False, min_new_samples: int = 3) -> Dict[str, Any]:
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
                class_weight='balanced',
                random_state=42,
                verbose=-1
            )
        else:
            base_clf = HistGradientBoostingClassifier(
                max_iter=120,
                max_depth=3,
                learning_rate=0.04,
                min_samples_leaf=5,
                class_weight='balanced',
                random_state=42
            )

        # Use isotonic calibration for true empirical monotonic probability calibration
        calib_method = 'isotonic' if len(X) >= 80 else 'sigmoid'
        calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method=calib_method, cv=3)
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

        # Save Dedicated Per-Coin Meta-Classifiers where history >= 5 resolved trades
        per_coin_trained = 0
        if 'symbol' in full_raw.columns:
            for sym, sym_df in full_raw.groupby('symbol'):
                clean_sym = sym.replace('/', '_').replace(':', '_')
                sym_feat = extract_features_from_records(sym_df)
                if len(sym_feat) >= 5:
                    try:
                        for col in feature_cols:
                            if col not in sym_feat.columns:
                                sym_feat[col] = 0.0
                        s_X = sym_feat[feature_cols].replace([np.inf, -np.inf], 0.0).fillna(0.0)
                        s_y = sym_feat['target']
                        if len(s_y.unique()) > 1:
                            s_base = HistGradientBoostingClassifier(max_iter=80, max_depth=2, min_samples_leaf=2, random_state=42)
                            s_cal = CalibratedClassifierCV(estimator=s_base, method='sigmoid', cv=2)
                            s_cal.fit(s_X, s_y)
                            m_to_save = s_cal
                        else:
                            single_cls = int(s_y.iloc[0])
                            m_to_save = SingleClassPriorModel(target_class=single_cls, sample_size=len(sym_feat))
                        
                        coin_dir = os.path.join(MODELS_DIR, "per_coin", clean_sym)
                        os.makedirs(coin_dir, exist_ok=True)
                        coin_meta_path = os.path.join(coin_dir, "meta_classifier.joblib")
                        
                        joblib.dump({
                            'model': m_to_save,
                            'feature_cols': feature_cols,
                            'symbol': sym,
                            'sample_size': len(sym_feat),
                            'trained_at_utc': datetime.now(timezone.utc).isoformat()
                        }, coin_meta_path)
                        per_coin_trained += 1
                    except Exception:
                        pass

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
            "per_coin_models_count": per_coin_trained,
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

        print(f"[MODEL RETRAIN] Retraining completed successfully! Samples: {total_resolved}, Acc: {acc*100:.1f}%, AUC: {auc:.3f}, Per-Coin: {per_coin_trained}")
        return {
            "success": True,
            "message": f"Model retrained successfully ({per_coin_trained} per-coin models created).",
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


def check_and_trigger_async(force: bool = False, min_new_samples: int = 3):
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
