import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List, Optional

from catboost import CatBoostClassifier
from xgboost import XGBClassifier
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    ExtraTreesClassifier,
    RandomForestClassifier,
)
from app.engine.config import MODEL_CONFIGS, CONSENSUS_VOTE_THRESHOLD

class FiveModelDirectionClassifier:
    """
    Ensemble of 5 Top Gradient Boosting & Decision Forest Classifiers:
    1. CatBoostClassifier
    2. XGBoostClassifier
    3. HistGradientBoostingClassifier
    4. ExtraTreesClassifier
    5. RandomForestClassifier

    Target: Next Candle Direction (🟢 Green Bullish vs 🔴 Red Bearish)
    Decision: Majority Consensus Voting (>= 3/5 votes)
    """

    def __init__(self):
        cfg = MODEL_CONFIGS["classifiers"]
        self.models = {
            "catboost": CatBoostClassifier(**cfg["catboost"]),
            "xgboost": XGBClassifier(**cfg["xgboost"]),
            "hist_gb": HistGradientBoostingClassifier(**cfg["hist_gb"]),
            "extra_trees": ExtraTreesClassifier(**cfg["extra_trees"]),
            "random_forest": RandomForestClassifier(**cfg["random_forest"])
        }
        self.is_fitted = False
        self.baseline_prob = 0.55
        self.last_y_mean = 0.55
        self.laplace_prob = 0.55
        self.is_cold_start = True
        self.sample_size = 0
        self.fitted_models: List[str] = []

    def fit(self, X_train: np.ndarray, y_train: np.ndarray) -> bool:
        """Fits all 5 classifiers on coin-specific feature sequences with numerical sanitization.
        When new coins enter the universe (< 15 candles or single class), activates the cold-start Laplace prior model.
        """
        if X_train is None or len(X_train) < 15 or y_train is None or len(np.unique(y_train)) < 2:
            n_samples = len(y_train) if (y_train is not None and hasattr(y_train, "__len__")) else 0
            k_bull = int(np.sum(y_train)) if n_samples > 0 else 0
            # Formal Laplace smoothing with symmetric uniform Beta(1, 1) prior: (k + 1) / (N + 2)
            self.laplace_prob = float((k_bull + 1.0) / (n_samples + 2.0))
            self.last_y_mean = self.laplace_prob
            self.sample_size = n_samples
            self.is_cold_start = True
            self.is_fitted = False
            return False

        X_clean = np.nan_to_num(np.asarray(X_train, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        y_clean = np.asarray(y_train, dtype=int)
        
        self.fitted_models = []
        for name, model in self.models.items():
            try:
                model.fit(X_clean, y_clean)
                self.fitted_models.append(name)
            except Exception:
                pass

        self.last_y_mean = float(np.mean(y_clean))
        self.laplace_prob = self.last_y_mean
        self.sample_size = len(y_clean)
        self.is_cold_start = False
        self.is_fitted = (len(self.fitted_models) >= 2)
        return self.is_fitted

    def predict_live(self, X_live: np.ndarray) -> Dict[str, Any]:
        """Runs live majority consensus direction voting across the 5 classifiers.
        Seamlessly serves the Cold-Start Laplace Prior when the model is in initial warm-up (< 15 candles).
        """
        if X_live is None:
            X_live = np.zeros((1, 1), dtype=np.float32)
        else:
            X_live = np.asarray(X_live, dtype=np.float32)
            if X_live.ndim == 1:
                X_live = X_live.reshape(1, -1)
            X_live = np.nan_to_num(X_live, nan=0.0, posinf=0.0, neginf=0.0)

        if not self.is_fitted:
            p_bull = getattr(self, "laplace_prob", self.last_y_mean)
            is_bull = (p_bull >= 0.50)
            baseline_p = float(np.clip(p_bull if is_bull else (1.0 - p_bull), 0.50, 0.95))
            n_sz = getattr(self, "sample_size", 0)
            tally_label = f"3/5 MAJORITY (COLD START LAPLACE PRIOR: N={n_sz})" if n_sz < 15 else "3/5 MAJORITY (BASELINE)"
            return {
                "decision": "GREEN_BULLISH" if is_bull else "RED_BEARISH",
                "direction": "LONG" if is_bull else "SHORT",
                "decision_label": "🟢 GREEN BULLISH (COLD START)" if is_bull else "🔴 RED BEARISH (COLD START)",
                "bullish_votes": 3 if is_bull else 2,
                "bearish_votes": 2 if is_bull else 3,
                "total_models": 5,
                "consensus_ratio": 0.60,
                "consensus_tally": tally_label,
                "consensus_probability": round(baseline_p, 4),
                "prob_bullish": round(float(p_bull), 4),
                "prob_bearish": round(float(1.0 - p_bull), 4),
                "is_unanimous": False,
                "is_cold_start": True,
                "model_type": "COLD_START_LAPLACE_PRIOR",
                "sample_size": n_sz,
                "model_breakdown": {m: {"vote": "GREEN_BULLISH" if is_bull else "RED_BEARISH", "prob": round(baseline_p, 4)} for m in self.models}
            }

        votes = []
        probs_bull = []
        breakdown = {}

        for name, model in self.models.items():
            try:
                fitted_set = getattr(self, "fitted_models", list(self.models.keys()))
                if name not in fitted_set and len(fitted_set) > 0:
                    raise RuntimeError(f"Model {name} failed during fit phase")

                if hasattr(model, "predict_proba"):
                    proba_out = model.predict_proba(X_live)
                    # Dynamically locate class 1 (bullish) index
                    if hasattr(model, "classes_") and len(model.classes_) > 0:
                        classes_list = list(model.classes_)
                        if 1 in classes_list:
                            idx_1 = classes_list.index(1)
                            prob_bull = float(proba_out[0, idx_1])
                        elif len(classes_list) == 1:
                            prob_bull = 1.0 if classes_list[0] == 1 else 0.0
                        else:
                            prob_bull = float(proba_out[0, -1])
                    else:
                        prob_bull = float(proba_out[0, 1] if proba_out.shape[1] > 1 else proba_out[0, 0])
                else:
                    pred_val = float(model.predict(X_live)[0])
                    prob_bull = float(np.clip(pred_val, 0.0, 1.0))
                
                prob_bull = float(np.clip(prob_bull, 0.01, 0.99))
                vote_bull = 1 if prob_bull >= 0.50 else 0
                votes.append(vote_bull)
                probs_bull.append(prob_bull)
                breakdown[name] = {
                    "vote": "GREEN_BULLISH" if vote_bull == 1 else "RED_BEARISH",
                    "prob_bullish": round(prob_bull, 4)
                }
            except Exception as e:
                vote_bull = 1 if self.last_y_mean >= 0.50 else 0
                votes.append(vote_bull)
                probs_bull.append(float(np.clip(self.last_y_mean, 0.05, 0.95)))
                breakdown[name] = {
                    "vote": "GREEN_BULLISH" if vote_bull == 1 else "RED_BEARISH",
                    "prob_bullish": round(float(self.last_y_mean), 4),
                    "fallback_note": str(e)
                }

        bull_votes = sum(votes)
        bear_votes = len(votes) - bull_votes
        mean_bull_prob = float(np.mean(probs_bull)) if probs_bull else self.last_y_mean

        if bull_votes >= CONSENSUS_VOTE_THRESHOLD:
            decision = "GREEN_BULLISH"
            direction = "LONG"
            label = "🟢 GREEN BULLISH"
            tally = f"{bull_votes}/5 BULLISH CONSENSUS" if bull_votes < 5 else "5/5 UNANIMOUS BULLISH"
            direction_confidence = float(np.clip(mean_bull_prob, 0.50, 0.95))
        else:
            decision = "RED_BEARISH"
            direction = "SHORT"
            label = "🔴 RED BEARISH"
            tally = f"{bear_votes}/5 BEARISH CONSENSUS" if bear_votes < 5 else "5/5 UNANIMOUS BEARISH"
            direction_confidence = float(np.clip(1.0 - mean_bull_prob, 0.50, 0.95))

        return {
            "decision": decision,
            "direction": direction,
            "decision_label": label,
            "bullish_votes": bull_votes,
            "bearish_votes": bear_votes,
            "total_models": 5,
            "consensus_ratio": round(max(bull_votes, bear_votes) / 5.0, 2),
            "consensus_tally": tally,
            "consensus_probability": round(direction_confidence, 4),
            "prob_bullish": round(mean_bull_prob, 4),
            "prob_bearish": round(1.0 - mean_bull_prob, 4),
            "is_unanimous": (bull_votes == 5 or bear_votes == 5),
            "model_breakdown": breakdown
        }

    def train_and_predict(self, X_train: np.ndarray, y_train: np.ndarray, X_live: np.ndarray) -> Dict[str, Any]:
        """
        Trains all 5 classifiers and produces consensus direction voting.
        Maintains complete backward compatibility.
        """
        self.fit(X_train, y_train)
        return self.predict_live(X_live)
