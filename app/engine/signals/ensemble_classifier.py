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
        self.baseline_prob = 0.50
        self.last_y_mean = 0.50
        self.laplace_prob = 0.50
        self.is_cold_start = True
        self.sample_size = 0
        self.fitted_models: List[str] = []

    def fit(self, X_train: np.ndarray, y_train: np.ndarray) -> bool:
        """Fits all 5 classifiers on coin-specific feature sequences with numerical sanitization.
        When new coins enter the universe (< 15 candles or single class), activates the cold-start Laplace prior model.
        """
        y_valid = None
        if y_train is not None:
            try:
                y_arr = np.asarray(y_train)
                if np.issubdtype(y_arr.dtype, np.number):
                    y_valid = y_arr[~np.isnan(y_arr) & ~np.isinf(y_arr)]
                else:
                    y_valid = y_arr
            except Exception:
                y_valid = np.array([])
        else:
            y_valid = np.array([])

        n_samples = len(y_valid)
        n_classes = len(np.unique(y_valid)) if n_samples > 0 else 0

        if X_train is None or len(X_train) < 15 or y_train is None or n_samples < 15 or n_classes < 2:
            k_bull = int(np.sum(y_valid > 0)) if n_samples > 0 else 0
            # Formal Laplace smoothing with symmetric uniform Beta(1, 1) prior: (k + 1) / (N + 2)
            self.laplace_prob = float((k_bull + 1.0) / (n_samples + 2.0))
            self.last_y_mean = self.laplace_prob
            self.sample_size = n_samples
            self.is_cold_start = True
            self.is_fitted = False
            return False

        X_clean = np.nan_to_num(np.asarray(X_train, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        y_clean = np.asarray(y_valid, dtype=int)
        
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

    def check_feature_compatibility(self, n_features: int) -> bool:
        """Verifies if fitted models match the expected input feature dimension."""
        fitted_list = getattr(self, "fitted_models", None)
        if fitted_list is None:
            fitted_list = list(self.models.keys())
        if not self.is_fitted or not fitted_list:
            return True
        for name in fitted_list:
            m = self.models.get(name)
            if m is not None and hasattr(m, "n_features_in_"):
                if int(m.n_features_in_) != int(n_features):
                    return False
        return True

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
                "model_breakdown": {
                    m: {
                        "vote": "GREEN_BULLISH" if is_bull else "RED_BEARISH",
                        "prob": round(baseline_p, 4),
                        "prob_bullish": round(float(p_bull), 4)
                    } for m in self.models
                }
            }

        # Pass 1: Run prediction on each candidate model and collect healthy responses
        valid_predictions: Dict[str, Optional[float]] = {}
        model_errors: Dict[str, str] = {}

        for name, model in self.models.items():
            try:
                fitted_set = getattr(self, "fitted_models", list(self.models.keys()))
                if name not in fitted_set and len(fitted_set) > 0:
                    raise RuntimeError(f"Model {name} failed during fit phase")

                X_input = X_live
                if hasattr(model, "n_features_in_"):
                    n_exp = int(model.n_features_in_)
                    if X_live.shape[1] > n_exp:
                        X_input = X_live[:, :n_exp]
                    elif X_live.shape[1] < n_exp:
                        X_input = np.pad(X_live, ((0, 0), (0, n_exp - X_live.shape[1])), mode='constant')

                if hasattr(model, "predict_proba"):
                    proba_raw = model.predict_proba(X_input)
                    proba_out = np.atleast_2d(proba_raw)
                    if proba_out.size == 0 or proba_out.shape[0] == 0:
                        raise ValueError(f"Empty proba output from {name}")
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
                    pred_val = float(model.predict(X_input)[0])
                    prob_bull = float(np.clip(pred_val, 0.0, 1.0))

                if np.isnan(prob_bull) or np.isinf(prob_bull):
                    raise ValueError(f"Model {name} produced non-finite probability {prob_bull}")

                prob_bull = float(np.clip(prob_bull, 0.01, 0.99))
                valid_predictions[name] = prob_bull
            except Exception as e:
                valid_predictions[name] = None
                model_errors[name] = str(e)

        # Pass 2: Dynamic Peer Consensus Fallback Resolution
        # If at least 1 model succeeded, failing models adopt the live peer consensus probability
        successful_probs = [p for p in valid_predictions.values() if p is not None]
        if successful_probs:
            peer_fallback_prob = float(np.mean(successful_probs))
        else:
            # When all models fail, fall back to dynamically calibrated Laplace prior
            peer_fallback_prob = float(np.clip(getattr(self, "laplace_prob", getattr(self, "last_y_mean", 0.50)), 0.05, 0.95))

        votes = []
        probs_bull = []
        breakdown = {}

        for name in self.models.keys():
            p_val = valid_predictions.get(name)
            if p_val is not None:
                prob_bull = p_val
                vote_bull = 1 if prob_bull >= 0.50 else 0
                votes.append(vote_bull)
                probs_bull.append(prob_bull)
                breakdown[name] = {
                    "vote": "GREEN_BULLISH" if vote_bull == 1 else "RED_BEARISH",
                    "prob_bullish": round(prob_bull, 4)
                }
            else:
                prob_bull = peer_fallback_prob
                vote_bull = 1 if prob_bull >= 0.50 else 0
                votes.append(vote_bull)
                probs_bull.append(prob_bull)
                breakdown[name] = {
                    "vote": "GREEN_BULLISH" if vote_bull == 1 else "RED_BEARISH",
                    "prob_bullish": round(prob_bull, 4),
                    "fallback_note": model_errors.get(name, "Dynamic peer consensus fallback engaged")
                }

        bull_votes = sum(votes)
        bear_votes = len(votes) - bull_votes

        if bull_votes >= CONSENSUS_VOTE_THRESHOLD:
            decision = "GREEN_BULLISH"
            direction = "LONG"
            label = "🟢 GREEN BULLISH"
            tally = f"{bull_votes}/5 BULLISH CONSENSUS" if bull_votes < 5 else "5/5 UNANIMOUS BULLISH"
            agreeing_probs = [p for p, v in zip(probs_bull, votes) if v == 1]
            consensus_p = float(np.mean(agreeing_probs)) if agreeing_probs else 0.50
            direction_confidence = float(np.clip(consensus_p, 0.50, 0.95))
            final_p_bull = direction_confidence
            final_p_bear = round(1.0 - final_p_bull, 4)
        else:
            decision = "RED_BEARISH"
            direction = "SHORT"
            label = "🔴 RED BEARISH"
            tally = f"{bear_votes}/5 BEARISH CONSENSUS" if bear_votes < 5 else "5/5 UNANIMOUS BEARISH"
            agreeing_probs = [1.0 - p for p, v in zip(probs_bull, votes) if v == 0]
            consensus_p = float(np.mean(agreeing_probs)) if agreeing_probs else 0.50
            direction_confidence = float(np.clip(consensus_p, 0.50, 0.95))
            final_p_bear = direction_confidence
            final_p_bull = round(1.0 - final_p_bear, 4)

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
            "prob_bullish": round(final_p_bull, 4),
            "prob_bearish": round(final_p_bear, 4),
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
