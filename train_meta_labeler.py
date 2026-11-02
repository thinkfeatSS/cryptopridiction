import os
import sys
import io
import math
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone

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

def extract_features(df: pd.DataFrame) -> pd.DataFrame:
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
            
            # 2. Numeric features
            conviction = float(row.get('conviction_pct', 70.0) or 70.0)
            
            exp_ret_raw = str(row.get('expected_return_pct', '0.0')).replace('%', '').replace('+', '').strip()
            exp_ret = float(exp_ret_raw) if exp_ret_raw not in ['', 'nan', 'None'] else 0.0

            # Quality grade numeric
            grade_str = str(row.get('quality_grade', ''))
            is_a_plus = 1.0 if "A+" in grade_str else 0.0
            
            # Horizon encoding aligned with institutional market structure (15M=Scalp, 1H/4H=Swing/Intraday, 24H+=Macro)
            horizon_str = str(row.get('horizon', '')).lower()
            is_scalp = 1.0 if any(k in horizon_str for k in ["scalp", "5m", "15m", "30m"]) else 0.0
            is_swing = 1.0 if any(k in horizon_str for k in ["swing", "intraday", "1h", "4h", "12h"]) else 0.0
            is_macro = 1.0 if any(k in horizon_str for k in ["macro", "24h", "1d", "2d", "3d", "4d", "7d", "15d", "30d", "week", "month", "48h", "72h"]) else 0.0
            
            # Direction
            direction_str = str(row.get('direction', '')).upper()
            is_long = 1.0 if direction_str == "LONG" or "BULLISH" in direction_str else 0.0
            
            # Decision setup type
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
            
            # Rank (e.g. "#1" -> 1)
            rank_raw = str(row.get('rank', '#1')).replace('#', '').strip()
            try:
                rank = float(rank_raw)
            except Exception:
                rank = 1.0

            # TP1 vs SL distance ratio using UN-RATCHETED initial stop loss (eliminates lookahead bias)
            entry_p = float(row.get('entry_price', 1.0) or 1.0)
            tp1_p = float(row.get('tp1_price', 1.0) or 1.0)
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
            is_meme = 1.0 if (clean_base_sym in MEME_AND_SHITCOIN_BASES or any(m in clean_base_sym for m in ["SHIB", "PEPE", "BONK", "DOGE", "FLOKI", "MEME", "WIF", "BOME"])) else 0.0

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

def train_and_save_meta_classifier():
    """Loads historical CSV records, trains the Meta-Labeling model, and saves joblib artifact."""
    print("=" * 80)
    print("[META-LABELER] Training Quantitative Secondary Meta-Labeling Classifier...")
    print("=" * 80)
    
    # Collect data from available sources
    dfs = []
    candidates = [
        "export_app_data/live_container_trader_signals_tracker.csv",
        "export_app_data/historical_meta_training_signals.csv",
        "latest_signals_from_container.csv",
        "latest_vps_signals.csv",
        "user_pasted_signals.csv",
        "vps_downloaded_signals.csv",
        "downloaded_signals.csv",
        "today_trader_signals_tracker.csv",
        "trader_signals_tracker.csv",
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
            n_estimators=140,
            max_depth=3,
            num_leaves=8,
            learning_rate=0.035,
            subsample=0.85,
            colsample_bytree=0.80,
            min_child_samples=5,
            class_weight='balanced',
            random_state=42,
            n_jobs=2,
            verbose=-1
        )
    else:
        base_clf = HistGradientBoostingClassifier(
            max_iter=140,
            max_depth=3,
            learning_rate=0.035,
            min_samples_leaf=5,
            class_weight='balanced',
            random_state=42
        )
        
    # Fit base classifier & calibrate probabilities via Sigmoid / Isotonic
    calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3, n_jobs=1)
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
    
    # Save Global Model Bundle with metadata and feature schema
    bundle = {
        'model': calibrated_clf,
        'feature_cols': feature_cols,
        'trained_at_utc': datetime.now(timezone.utc).isoformat(),
        'sample_size': len(feat_df),
        'baseline_win_rate': float(y.mean()),
        'auc_score': float(auc)
    }
    
    joblib.dump(bundle, META_MODEL_PATH)
    print(f"[SAVED] Global Meta-Labeler Successfully Saved to: {META_MODEL_PATH}")

    # Train Dedicated Per-Coin Meta-Classifiers where history >= 5 resolved trades
    if 'symbol' in full_raw.columns:
        for sym, sym_df in full_raw.groupby('symbol'):
            clean_sym = sym.replace('/', '_').replace(':', '_')
            sym_feat = extract_features(sym_df)
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
                    print(f"  └─ Trained dedicated per-coin meta-classifier for {sym} ({len(sym_feat)} samples)")
                except Exception as e:
                    pass

    print()
    return True

if __name__ == "__main__":
    train_and_save_meta_classifier()
