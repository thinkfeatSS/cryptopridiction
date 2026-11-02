import os
import time
import threading
import warnings
import joblib
import numpy as np
from typing import Dict, Any, Tuple, Optional, List

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

from app.engine.config import MODELS_DIR
from .ensemble_classifier import FiveModelDirectionClassifier
from .ensemble_regressor import FiveModelPriceRegressor

class PerCoinModelRegistry:
    """
    Dedicated Model Registry for Per-Coin Classifiers & Regressors.
    Guarantees strict asset isolation:
    - Every coin has its own separate 5 Classifiers (Direction Voting) per timeframe.
    - Every coin has its own separate 5 Regressors (Price Target Selection) per timeframe.
    - Persisted to disk under: models_export_v3/per_coin/{clean_symbol}/models_{tf}.joblib
    - Fast in-memory cache for high-throughput live scans.
    """

    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(PerCoinModelRegistry, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, base_models_dir: str = None):
        if getattr(self, "_initialized", False):
            return
        self.base_dir = base_models_dir or MODELS_DIR
        self.per_coin_dir = os.path.join(self.base_dir, "per_coin")
        os.makedirs(self.per_coin_dir, exist_ok=True)

        self._lock = threading.Lock()
        # Memory cache: {f"{clean_sym}_{tf}": (clf_ensemble, reg_ensemble, fit_ts, candle_ts)}
        self._cache: Dict[str, Tuple[FiveModelDirectionClassifier, FiveModelPriceRegressor, float, int]] = {}
        self._initialized = True
        self.preload_existing_models()

    def preload_existing_models(self) -> int:
        """Preloads existing trained models from disk into memory cache on daemon startup."""
        loaded_count = 0
        if not os.path.exists(self.per_coin_dir):
            return 0
        try:
            for coin_name in os.listdir(self.per_coin_dir):
                coin_path = os.path.join(self.per_coin_dir, coin_name)
                if not os.path.isdir(coin_path):
                    continue
                for f in os.listdir(coin_path):
                    if f.startswith("models_") and f.endswith(".joblib"):
                        tf = f.replace("models_", "").replace(".joblib", "")
                        cache_key = f"{coin_name}_{tf}"
                        full_path = os.path.join(coin_path, f)
                        try:
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore")
                                bundle = joblib.load(full_path)
                            c_clfs = bundle.get("classifiers")
                            c_regs = bundle.get("regressors")
                            b_fit_ts = bundle.get("fit_timestamp", 0.0)
                            b_candle_ts = bundle.get("last_candle_ts", 0)
                            if c_clfs and c_regs:
                                with self._lock:
                                    self._cache[cache_key] = (c_clfs, c_regs, b_fit_ts, b_candle_ts)
                                loaded_count += 1
                        except Exception:
                            continue
            if loaded_count > 0:
                try:
                    print(f"[MODEL REGISTRY 🧠] Preloaded {loaded_count} per-coin model bundles into memory cache from disk.", flush=True)
                except Exception:
                    print(f"[MODEL REGISTRY] Preloaded {loaded_count} per-coin model bundles into memory cache from disk.", flush=True)
        except Exception as e:
            try:
                print(f"[MODEL REGISTRY ⚠️] Preload warning: {e}", flush=True)
            except Exception:
                print(f"[MODEL REGISTRY] Preload warning: {e}", flush=True)
        return loaded_count

    def get_clean_symbol(self, symbol: str) -> str:
        """Standardizes pair symbol to safe filesystem name (e.g., BTC/USDT -> BTC_USDT)."""
        return symbol.replace("/", "_").replace(":USDT", "").replace(":", "_").strip()

    def get_coin_dir(self, symbol: str) -> str:
        """Returns dedicated disk directory for a given coin, creating it if needed."""
        clean_sym = self.get_clean_symbol(symbol)
        d = os.path.join(self.per_coin_dir, clean_sym)
        os.makedirs(d, exist_ok=True)
        return d

    def get_model_path(self, symbol: str, tf: str) -> str:
        """Returns path to dedicated timeframe model bundle for this coin."""
        return os.path.join(self.get_coin_dir(symbol), f"models_{tf}.joblib")

    def get_or_train_coin_models(
        self,
        symbol: str,
        tf: str,
        X_train: np.ndarray,
        y_train_dir: np.ndarray,
        y_train_ret: np.ndarray,
        last_candle_ts: int,
        ttl_seconds: float
    ) -> Tuple[FiveModelDirectionClassifier, FiveModelPriceRegressor, bool]:
        """
        Retrieves dedicated models for this coin and timeframe, or trains them fresh.
        Returns (clf_ensemble, reg_ensemble, is_freshly_trained).
        Seamlessly handles new coin cold-start via Laplace prior models and promotes to
        full 5-model ensemble convergence as soon as 15+ candles accumulate.
        """
        clean_sym = self.get_clean_symbol(symbol)
        cache_key = f"{clean_sym}_{tf}"
        now_ts = time.time()
        n_samples = len(X_train) if X_train is not None else 0

        # 1. Check in-memory cache
        with self._lock:
            if cache_key in self._cache:
                c_clfs, c_regs, c_fit_ts, c_candle_ts = self._cache[cache_key]
                is_cached_cold = getattr(c_clfs, "is_cold_start", False)
                # If cached was cold-start but now we have >= 15 candles, promote to full fit!
                if not (is_cached_cold and n_samples >= 15):
                    if (now_ts - c_fit_ts < ttl_seconds) and (last_candle_ts == c_candle_ts):
                        return c_clfs, c_regs, False

        # 2. Check disk persistence
        disk_path = self.get_model_path(symbol, tf)
        if os.path.exists(disk_path):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    bundle = joblib.load(disk_path)
                b_candle_ts = bundle.get("last_candle_ts", 0)
                b_fit_ts = bundle.get("fit_timestamp", 0.0)
                c_clfs = bundle.get("classifiers")
                c_regs = bundle.get("regressors")
                is_disk_cold = bundle.get("is_cold_start", False) or getattr(c_clfs, "is_cold_start", False)

                # Only reuse disk cache if not pending cold-start promotion
                if not (is_disk_cold and n_samples >= 15):
                    if c_clfs and c_regs and (last_candle_ts == b_candle_ts) and (now_ts - b_fit_ts < ttl_seconds):
                        with self._lock:
                            self._cache[cache_key] = (c_clfs, c_regs, b_fit_ts, b_candle_ts)
                        return c_clfs, c_regs, False
            except Exception:
                pass # Corrupt or unreadable disk file -> re-fit cleanly

        # 3. Train strictly separate models for this coin on its own data
        clf_ensemble = FiveModelDirectionClassifier()
        reg_ensemble = FiveModelPriceRegressor()

        clf_ensemble.fit(X_train, y_train_dir)
        reg_ensemble.fit(X_train, y_train_ret)

        # 4. Save to coin's dedicated disk directory atomically
        self.save_coin_models(
            symbol=symbol,
            tf=tf,
            classifiers=clf_ensemble,
            regressors=reg_ensemble,
            last_candle_ts=last_candle_ts,
            train_samples=len(X_train) if X_train is not None else 0,
            fit_timestamp=now_ts
        )

        with self._lock:
            self._cache[cache_key] = (clf_ensemble, reg_ensemble, now_ts, last_candle_ts)

        return clf_ensemble, reg_ensemble, True

    def save_coin_models(
        self,
        symbol: str,
        tf: str,
        classifiers: FiveModelDirectionClassifier,
        regressors: FiveModelPriceRegressor,
        last_candle_ts: int,
        train_samples: int,
        fit_timestamp: float = None
    ) -> bool:
        """Atomically saves this coin's trained classification and regression ensembles."""
        disk_path = self.get_model_path(symbol, tf)
        tmp_path = disk_path + ".tmp"
        is_cold = getattr(classifiers, "is_cold_start", False)
        bundle = {
            "symbol": symbol,
            "clean_symbol": self.get_clean_symbol(symbol),
            "timeframe": tf,
            "classifiers": classifiers,
            "regressors": regressors,
            "last_candle_ts": last_candle_ts,
            "fit_timestamp": fit_timestamp or time.time(),
            "train_samples": train_samples,
            "is_cold_start": is_cold,
            "models_type": "COLD_START_LAPLACE_PRIOR" if is_cold else "PER_COIN_DEDICATED"
        }
        try:
            joblib.dump(bundle, tmp_path)
            os.replace(tmp_path, disk_path)
            return True
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False

    def get_coin_status(self, symbol: str) -> Dict[str, Any]:
        """Returns disk inspection metadata for all models trained for this coin."""
        clean_sym = self.get_clean_symbol(symbol)
        coin_dir = self.get_coin_dir(symbol)
        files = os.listdir(coin_dir) if os.path.exists(coin_dir) else []
        tf_models = [f.replace("models_", "").replace(".joblib", "") for f in files if f.startswith("models_") and f.endswith(".joblib")]
        has_meta = "meta_classifier.joblib" in files

        return {
            "symbol": symbol,
            "clean_symbol": clean_sym,
            "coin_dir": coin_dir,
            "trained_timeframes": tf_models,
            "timeframes_count": len(tf_models),
            "has_dedicated_meta_labeler": has_meta,
            "total_model_files": len(files)
        }
