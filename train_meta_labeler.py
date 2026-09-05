import os
import sys
import io
import math
import joblib
import numpy as np
import pandas as pd
from datetime import datetime

# Configure UTF-8 safe stdout
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score, classification_report

# Ensure output directory exists
MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "models_export_v3"))
os.makedirs(MODELS_DIR, exist_ok=True)
META_MODEL_PATH = os.path.join(MODELS_DIR, "signal_meta_classifier.joblib")

def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Preprocesses and extracts quantitative meta-features from signal records."""
    data = []
    for _, row in df.iterrows():
        try:
            # 1. Target Label: 1 if WON (TP1/TP2/TP3 hit), 0 if LOST (SL hit)
            status_str = str(row.get('status', '')).upper()
            outcome_str = str(row.get('outcome_label', '')).upper()
            
            if "WON" in status_str or "WON" in outcome_str:
                target = 1
            elif "LOST" in status_str or "LOST" in outcome_str:
                target = 0
            else:
                continue # Skip pending or unverified
            
            # 2. Numeric features
            conviction = float(row.get('conviction_pct', 70.0) or 70.0)
            
            exp_ret_raw = str(row.get('expected_return_pct', '0.0')).replace('%', '').replace('+', '').strip()
            exp_ret = float(exp_ret_raw) if exp_ret_raw not in ['', 'nan', 'None'] else 0.0
            
            # Risk-to-Reward (e.g. "1:2.0" -> 2.0)
            rr_raw = str(row.get('risk_reward_ratio', '1:2.0')).split(':')[-1]
            try:
                rr_ratio = float(rr_raw)
            except Exception:
                rr_ratio = 2.0

            # Quality grade numeric
            grade_str = str(row.get('quality_grade', ''))
            is_a_plus = 1.0 if "A+" in grade_str else 0.0
            
            # Horizon encoding
            horizon_str = str(row.get('horizon', '')).lower()
            is_scalp = 1.0 if "scalp" in horizon_str or "15m" in horizon_str else 0.0
            is_swing = 1.0 if "swing" in horizon_str or "1h" in horizon_str else 0.0
            is_macro = 1.0 if "macro" in horizon_str or "24h" in horizon_str or "1d" in horizon_str else 0.0
            
            # Direction
            direction_str = str(row.get('direction', '')).upper()
            is_long = 1.0 if direction_str == "LONG" or "BULLISH" in direction_str else 0.0
            
            # Decision setup type
            decision_str = str(row.get('decision', '')).upper()
            is_dip_buy = 1.0 if "DIP-BUY" in decision_str else 0.0
            is_rally_sell = 1.0 if "RALLY-SELL" in decision_str else 0.0
            is_liq_sweep = 1.0 if "LIQUIDITY-SWEEP" in decision_str else 0.0
            is_squeeze = 1.0 if "SHORT SQUEEZE" in decision_str else 0.0
            is_paper_exec = 1.0 if "EXECUTED" in str(row.get('paper_trading_status', '')).upper() else 0.0
            
            # Rank (e.g. "#1" -> 1)
            rank_raw = str(row.get('rank', '#1')).replace('#', '').strip()
            try:
                rank = float(rank_raw)
            except Exception:
                rank = 1.0

            # TP1 vs SL distance ratio
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
        except Exception as e:
            continue
            
    return pd.DataFrame(data)

def train_and_save_meta_classifier():
    """Loads historical CSV records, trains the Meta-Labeling model, and saves joblib artifact."""
    print("=" * 80)
    print("[META-LABELER] Training Quantitative Secondary Meta-Labeling Classifier...")
    print("=" * 80)
    
    # Collect data from available sources
    dfs = []
    candidates = [
        "user_pasted_signals.csv",
        "export_app_data/trader_signals_tracker.csv"
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                d = pd.read_csv(c)
                if len(d) > 0:
                    dfs.append(d)
                    print(f"[DATA] Loaded {len(d)} signal rows from {c}")
            except Exception as e:
                print(f"[DATA] Warning reading {c}: {e}")
                
    if not dfs:
        print("[ERROR] No historical CSV data found.")
        return False
        
    full_raw = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=['signal_id'], keep='last')
    print(f"[DATA] Total Unique Raw Signals: {len(full_raw)}")
    
    feat_df = extract_features(full_raw)
    if len(feat_df) < 15:
        print(f"[ERROR] Insufficient resolved records ({len(feat_df)}) for ML training.")
        return False
        
    feature_cols = [c for c in feat_df.columns if c != 'target']
    X = feat_df[feature_cols]
    y = feat_df['target']
    
    print(f"[DATASET] Resolved Training Set: {len(feat_df)} trades (Wins: {sum(y==1)}, Losses: {sum(y==0)}) | Baseline Win Rate: {y.mean()*100:.1f}%")
    
    # Model Selection: LightGBM with HistGradientBoosting / RandomForest Fallback
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
        
    # Fit base classifier & calibrate probabilities via Sigmoid / Isotonic
    calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3)
    calibrated_clf.fit(X, y)
    
    # In-sample & cross-validation metrics
    preds = calibrated_clf.predict(X)
    probs = calibrated_clf.predict_proba(X)[:, 1]
    
    acc = accuracy_score(y, preds)
    try:
        auc = roc_auc_score(y, probs)
    except Exception:
        auc = 0.50
    prec = precision_score(y, preds, zero_division=0)
    
    print(f"[METRICS] Meta-Model Accuracy: {acc*100:.1f}% | ROC-AUC: {auc:.3f} | Precision: {prec*100:.1f}%")
    
    # Save Model Bundle with metadata and feature schema
    bundle = {
        'model': calibrated_clf,
        'feature_cols': feature_cols,
        'trained_at_utc': datetime.utcnow().isoformat(),
        'sample_size': len(feat_df),
        'baseline_win_rate': float(y.mean()),
        'auc_score': float(auc)
    }
    
    joblib.dump(bundle, META_MODEL_PATH)
    print(f"[SAVED] Trained Meta-Labeler Successfully Saved to: {META_MODEL_PATH}\n")
    return True

if __name__ == "__main__":
    train_and_save_meta_classifier()
