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
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score, classification_report

# Ensure output directory exists
MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "models_export_v3"))
os.makedirs(MODELS_DIR, exist_ok=True)
META_MODEL_PATH = os.path.join(MODELS_DIR, "signal_meta_classifier.joblib")

from app.engine.signals.meta_labeler import (
    PurgedTimeSeriesSplit,
    SingleClassPriorModel,
    META_FEATURE_COLS
)


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
                continue  # Skip pending or unverified
                
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
            
            # 2. Structural & Economic features
            exp_ret_raw = str(row.get('expected_return_pct', '0.0')).replace('%', '').replace('+', '').strip()
            exp_ret = float(exp_ret_raw) if exp_ret_raw not in ['', 'nan', 'None'] else 0.0

            # Horizon encoding aligned with institutional market structure (15M=Scalp, 1H/4H=Swing/Intraday, 24H+=Macro)
            horizon_str = str(row.get('horizon', '')).upper()
            is_scalp = 1.0 if any(k in horizon_str for k in ["SCALP", "5M", "15M", "30M"]) else 0.0
            is_swing = 1.0 if any(k in horizon_str for k in ["1H", "DAY", "INTRADAY", "4H", "12H", "SWING"]) and not any(k in horizon_str for k in ["24H", "1D", "7D", "15D", "MACRO"]) else 0.0
            is_macro = 1.0 if any(k in horizon_str for k in ["24H", "1D", "2D", "3D", "4D", "7D", "15D", "30D", "WEEK", "MONTH", "48H", "72H", "MACRO"]) else 0.0
            
            # Direction
            direction_str = str(row.get('direction', '')).upper()
            is_long = 1.0 if direction_str in ["LONG", "BULLISH", "BUY"] else 0.0
            
            # Decision setup structural types
            decision_str = str(row.get('decision', '') or '').upper()
            strategy_str = str(row.get('canonical_strategy') or row.get('strategy') or '').upper()
            combined_meta_text = f"{decision_str} {strategy_str}"
            is_liq_sweep = 1.0 if ("LIQUIDITY-SWEEP" in combined_meta_text or "SWEEP" in combined_meta_text or "RECLAIM" in combined_meta_text or "LIQUIDITY" in combined_meta_text) else 0.0
            is_squeeze = 1.0 if ("SHORT SQUEEZE" in combined_meta_text or "SQUEEZE" in combined_meta_text or "COILING" in combined_meta_text) else 0.0
            is_order_block = 1.0 if (bool(row.get("is_order_block_signal")) or "ORDER-BLOCK" in combined_meta_text or "ORDER_BLOCK" in combined_meta_text or "POI" in combined_meta_text) else 0.0
            is_breaker_block = 1.0 if ("BREAKER-BLOCK" in combined_meta_text or "BREAKER" in combined_meta_text) else 0.0
            is_paper_exec = 1.0 if any(k in str(row.get('paper_trading_status', '')).upper() for k in ["EXECUTED", "ACTIVE", "TRUE"]) else 0.0
            
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

            from app.engine.config import is_meme_coin
            sym_str = str(row.get('symbol', '')).upper()
            is_meme = 1.0 if is_meme_coin(sym_str) else 0.0

            # 3. 7 Validated Market Microstructure Features
            def _get_row_num(keys, default=None):
                for k in keys:
                    if k in row:
                        val = row.get(k)
                        if val is not None and not pd.isna(val):
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                continue
                return default

            tb_num = _get_row_num(['f_taker_buy_ratio', 'taker_buy_ratio', 'taker_buy_ratio_5'], default=0.50)
            tb = float(tb_num if tb_num is not None else 0.50)
            cvd_num = _get_row_num(['f_cvd_divergence', 'cvd_surge_5', 'cvd_surge', 'cvd_val'])
            if cvd_num is not None:
                f_cvd_divergence = float(np.clip(cvd_num, -1.0, 1.0))
            else:
                f_cvd_divergence = float(np.clip((2.0 * tb - 1.0), -1.0, 1.0))

            obi_num = _get_row_num(['f_order_book_imbalance', 'order_book_imbalance', 'book_imbalance'])
            if obi_num is not None:
                f_order_book_imbalance = float(np.clip(obi_num, -1.0, 1.0))
            else:
                f_order_book_imbalance = float(np.clip((tb - 0.50) * 2.0, -1.0, 1.0))

            vr_num = _get_row_num(['f_volatility_ratio', 'volatility_ratio', 'expansion_ratio'])
            if vr_num is not None:
                f_volatility_ratio = float(np.clip(vr_num, 0.1, 5.0))
            else:
                f_volatility_ratio = float(np.clip(round((tp_pct + sl_pct) / 2.0, 2), 0.2, 5.0))

            f_taker_buy_ratio = float(np.clip(tb, 0.0, 1.0))

            lp_num = _get_row_num(['f_liquidity_proximity', 'liquidity_proximity', 'poi_distance_pct'])
            if lp_num is not None:
                f_liquidity_proximity = float(np.clip(abs(lp_num), 0.0, 10.0))
            else:
                f_liquidity_proximity = float(np.clip(round(min(tp_pct, sl_pct), 2), 0.1, 10.0))

            fd_num = _get_row_num(['f_funding_drag', 'funding_rate', 'funding_pct'])
            if fd_num is not None:
                f_funding_drag = float(np.clip(fd_num * 10000.0 if abs(fd_num) < 0.1 else fd_num, -50.0, 50.0))
            else:
                f_funding_drag = 1.0

            rvol_num = _get_row_num(['f_relative_volume', 'relative_volume', 'rvol', 'volume_surge_ratio'])
            if rvol_num is not None:
                f_relative_volume = float(np.clip(rvol_num, 0.05, 10.0))
            else:
                f_relative_volume = 1.0

            feat_dict = {
                # 7 Microstructure features
                'f_cvd_divergence': f_cvd_divergence,
                'f_order_book_imbalance': f_order_book_imbalance,
                'f_volatility_ratio': f_volatility_ratio,
                'f_taker_buy_ratio': f_taker_buy_ratio,
                'f_liquidity_proximity': f_liquidity_proximity,
                'f_funding_drag': f_funding_drag,
                'f_relative_volume': f_relative_volume,
                # Quantitative structural features
                'expected_return_pct': exp_ret,
                'risk_reward_ratio': clean_rr,
                'is_scalp': is_scalp,
                'is_swing': is_swing,
                'is_macro': is_macro,
                'is_long': is_long,
                'is_liq_sweep': is_liq_sweep,
                'is_squeeze': is_squeeze,
                'is_order_block': is_order_block,
                'is_breaker_block': is_breaker_block,
                'is_paper_exec': is_paper_exec,
                'is_meme': is_meme,
                'rank': rank,
                'tp_pct': round(tp_pct, 2),
                'sl_pct': round(sl_pct, 2),
                'tp_sl_ratio': clean_rr,
                # Target
                'target': target
            }
            data.append(feat_dict)
        except Exception:
            continue
            
    return pd.DataFrame(data)


def train_and_save_meta_classifier():
    """Loads historical CSV records, trains the Meta-Labeling model using Purged TimeSeriesSplit, and saves joblib artifact."""
    print("=" * 80)
    print("[META-LABELER] Training Quantitative Secondary Meta-Labeling Classifier (Microstructure v16)...")
    print("=" * 80)
    
    # Collect data from available sources
    dfs = []
    candidates = [
        "export_app_data/trader_signals_tracker.csv",
        "export_app_data/live_container_trader_signals_tracker.csv",
        "export_app_data/historical_meta_training_signals.csv",
        "latest_signals_from_container.csv",
        "latest_vps_signals.csv",
        "user_pasted_signals.csv",
        "vps_downloaded_signals.csv",
        "downloaded_signals.csv",
        "today_trader_signals_tracker.csv",
        "trader_signals_tracker.csv"
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
        
    feature_cols = META_FEATURE_COLS
    for col in feature_cols:
        if col not in feat_df.columns:
            feat_df[col] = 0.0

    X = feat_df[feature_cols].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    y = feat_df['target']
    
    print(f"[DATASET] Resolved Training Set: {len(feat_df)} trades (Wins: {sum(y==1)}, Losses: {sum(y==0)}) | Baseline Win Rate: {y.mean()*100:.1f}%")
    print(f"[DATASET] Active Microstructure Features ({len(feature_cols)}): {feature_cols}")
    
    # Model Selection: LightGBM with HistGradientBoosting Fallback
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
        
    # Fit base classifier & calibrate probabilities via Sigmoid with Purged TimeSeriesSplit (embargo=2%)
    cv_splitter = PurgedTimeSeriesSplit(n_splits=5, embargo_pct=0.02)
    calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=cv_splitter)
    calibrated_clf.fit(X, y)
    
    # In-sample metrics
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
                        n_coin_splits = min(3, max(2, len(s_X) // 5))
                        s_cv = PurgedTimeSeriesSplit(n_splits=n_coin_splits, embargo_pct=0.02)
                        s_cal = CalibratedClassifierCV(estimator=s_base, method='sigmoid', cv=s_cv)
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
                except Exception:
                    pass

    print()
    return True

if __name__ == "__main__":
    train_and_save_meta_classifier()
