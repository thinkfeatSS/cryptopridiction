"""
QUANT EDGE V16: Calibrated Probability & Multi-Target Path Model
Specifications:
- Section 3: G4 (Replace conviction with calibrated probability)
- Section 17: Probability Model:
    P(TP1 before SL), P(TP2 before SL), P(TP3 before SL), P(SL before TP1)
    P(TP1) + P(SL) ~ 1.0 for first target event
    Conditional: P(TP2) = P(TP1) * P(TP2 | TP1), P(TP3) = P(TP2) * P(TP3 | TP2)
- Section 18: Probability Calibration (Platt scaling & Isotonic mapping)
- Rule 6 & 7: Out-of-sample chronological evaluation, zero lookahead leakage
"""

import math
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass

@dataclass
class PathProbabilities:
    p_tp1: float              # P(TP1 before SL)
    p_tp2: float              # P(TP2 before SL)
    p_tp3: float              # P(TP3 before SL)
    p_sl: float               # P(SL before TP1)
    p_tp2_given_tp1: float = 0.65    # Conditional P(TP2 | TP1 reached)
    p_tp3_given_tp2: float = 0.55    # Conditional P(TP3 | TP2 reached)
    risk_reward: float = 2.0  # R:R geometry preserved for path modeling
    is_calibrated: bool = True
    calibration_method: str = "Platt_Scaling"


class ProbabilityCalibrator:
    """
    Transforms raw model output logits / raw probabilities into well-calibrated
    empirical win frequencies using historical empirical outcomes.
    Supports in-sample fitting, out-of-sample evaluation, and walk-forward verification.
    """

    def __init__(self, method: str = "platt", slope: float = 0.88, intercept: float = -0.05):
        self.method = method.lower()
        self.slope = slope
        self.intercept = intercept

    def calibrate(self, raw_prob: float) -> float:
        """
        Calibrates raw probability between 0.05 and 0.95 using fitted Platt or isotonic parameters.
        """
        p_clamped = max(0.01, min(0.99, raw_prob))

        if self.method == "platt":
            logit = math.log(p_clamped / (1.0 - p_clamped))
            calibrated_logit = (self.slope * logit) + self.intercept
            calibrated_p = 1.0 / (1.0 + math.exp(-calibrated_logit))
        elif self.method == "isotonic":
            if p_clamped < 0.30:
                calibrated_p = p_clamped * 0.85
            elif p_clamped < 0.70:
                calibrated_p = p_clamped
            else:
                calibrated_p = 0.70 + ((p_clamped - 0.70) * 0.75)
        else:
            calibrated_p = p_clamped

        return round(max(0.05, min(0.95, calibrated_p)), 4)

    def fit(self, y_prob: List[float], y_true: List[int], max_iter: int = 100, lr: float = 0.05, l2_reg: float = 0.01):
        """
        Fits Platt scaling coefficients (slope and intercept) via gradient descent
        on chronological training observations (y_prob, y_true).
        Minimizes cross-entropy with L2 regularization to prevent overfitting.
        """
        if len(y_prob) < 10 or len(y_prob) != len(y_true):
            return self

        # Extract clamped logits
        logits = []
        for p in y_prob:
            p_c = max(0.01, min(0.99, float(p)))
            logits.append(math.log(p_c / (1.0 - p_c)))

        w = float(self.slope)
        b = float(self.intercept)
        n = len(logits)

        for _ in range(max_iter):
            grad_w = 0.0
            grad_b = 0.0
            for z, y in zip(logits, y_true):
                pred_logit = (w * z) + b
                p_hat = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, pred_logit))))
                err = p_hat - float(y)
                grad_w += err * z
                grad_b += err

            grad_w = (grad_w / n) + (l2_reg * (w - 1.0))
            grad_b = (grad_b / n) + (l2_reg * b)

            w -= lr * grad_w
            b -= lr * grad_b

        # Constrain to stable bounds
        self.slope = max(0.10, min(3.0, w))
        self.intercept = max(-2.0, min(2.0, b))
        return self

    @staticmethod
    def evaluate_calibration(y_prob: List[float], y_true: List[int], n_bins: int = 10) -> Dict[str, Any]:
        """
        Evaluates probability calibration on out-of-sample data:
        - Brier score: Mean squared error of probabilities vs binary realizations (lower is better, baseline ~0.25).
        - Log loss: Negative log-likelihood (lower is better).
        - ECE: Expected Calibration Error across reliability bins.
        """
        if not y_prob or len(y_prob) != len(y_true):
            return {"brier_score": 0.25, "log_loss": 0.6931, "ece": 0.0, "sample_size": 0}

        n = len(y_prob)
        brier = sum((float(p) - float(y)) ** 2 for p, y in zip(y_prob, y_true)) / n

        ll_sum = 0.0
        for p, y in zip(y_prob, y_true):
            p_c = max(1e-6, min(1.0 - 1e-6, float(p)))
            y_f = float(y)
            ll_sum += - (y_f * math.log(p_c) + (1.0 - y_f) * math.log(1.0 - p_c))
        log_loss = ll_sum / n

        # Reliability diagram binning & ECE calculation
        bins: Dict[int, List[Tuple[float, int]]] = {i: [] for i in range(n_bins)}
        for p, y in zip(y_prob, y_true):
            b_idx = min(n_bins - 1, int(float(p) * n_bins))
            bins[b_idx].append((float(p), int(y)))

        ece = 0.0
        bin_stats = []
        for b_idx in range(n_bins):
            items = bins[b_idx]
            if items:
                b_size = len(items)
                avg_conf = sum(it[0] for it in items) / b_size
                avg_acc = sum(it[1] for it in items) / b_size
                ece += (b_size / n) * abs(avg_acc - avg_conf)
                bin_stats.append({
                    "bin": b_idx,
                    "count": b_size,
                    "avg_confidence": round(avg_conf, 4),
                    "empirical_accuracy": round(avg_acc, 4),
                    "calibration_gap": round(abs(avg_acc - avg_conf), 4)
                })

        return {
            "sample_size": n,
            "brier_score": round(brier, 4),
            "log_loss": round(log_loss, 4),
            "expected_calibration_error": round(ece, 4),
            "reliability_bins": bin_stats
        }

    @classmethod
    def walk_forward_calibrate(
        cls,
        chronological_pairs: List[Tuple[str, float, int]],
        initial_train_size: int = 50,
        step_size: int = 25
    ) -> Dict[str, Any]:
        """
        Executes strict chronological walk-forward out-of-sample calibration.
        Guarantees ZERO lookahead:
        For every test step, parameters are fitted exclusively on prior observations.
        """
        # Sort chronologically by timestamp
        sorted_pairs = sorted(chronological_pairs, key=lambda x: x[0])
        n = len(sorted_pairs)
        if n < initial_train_size + step_size:
            return {
                "status": "INSUFFICIENT_DATA",
                "sample_size": n,
                "required_minimum": initial_train_size + step_size
            }

        uncalibrated_oos_preds: List[float] = []
        calibrated_oos_preds: List[float] = []
        oos_actuals: List[int] = []

        curr_train_end = initial_train_size
        while curr_train_end < n:
            train_chunk = sorted_pairs[:curr_train_end]
            test_chunk = sorted_pairs[curr_train_end:curr_train_end + step_size]
            if not test_chunk:
                break

            train_probs = [item[1] for item in train_chunk]
            train_actuals = [item[2] for item in train_chunk]

            calibrator = cls(method="platt")
            calibrator.fit(train_probs, train_actuals)

            for _, raw_p, actual_y in test_chunk:
                cal_p = calibrator.calibrate(raw_p)
                uncalibrated_oos_preds.append(raw_p)
                calibrated_oos_preds.append(cal_p)
                oos_actuals.append(actual_y)

            curr_train_end += step_size

        eval_raw = cls.evaluate_calibration(uncalibrated_oos_preds, oos_actuals)
        eval_cal = cls.evaluate_calibration(calibrated_oos_preds, oos_actuals)

        return {
            "status": "VERIFIED_OOS",
            "out_of_sample_evaluations": len(oos_actuals),
            "uncalibrated_metrics": eval_raw,
            "calibrated_metrics": eval_cal,
            "brier_improvement_pct": round(((eval_raw["brier_score"] - eval_cal["brier_score"]) / max(1e-6, eval_raw["brier_score"])) * 100.0, 2),
            "ece_reduction_pct": round(((eval_raw["expected_calibration_error"] - eval_cal["expected_calibration_error"]) / max(1e-6, eval_raw["expected_calibration_error"])) * 100.0, 2)
        }


class ProbabilityPathModel:
    """
    Derives realistic multi-stage execution path probabilities for TP1, TP2, TP3, and SL.
    
    Model Design Note (Risk:Reward Geometry):
    In Quant Edge V16, `risk_reward` (ratio of TP1 distance to SL distance) is a primary
    input feature into the underlying ML classifier (`signal_meta_classifier`, see train_meta_labeler.py).
    Therefore, the incoming `raw_win_prob` ALREADY reflects the geometric hurdle difficulty
    of reaching TP1 before SL.
    To avoid double-counting hurdle penalties, `estimate_path_probabilities` preserves `risk_reward`
    for downstream Expected Value (EV) calculation and path trajectory recording, while relying
    on the calibrated probability for statistical integrity.
    """

    def __init__(self, calibrator: Optional[ProbabilityCalibrator] = None):
        self.calibrator = calibrator or ProbabilityCalibrator()

    def estimate_path_probabilities(
        self,
        raw_win_prob: float,
        risk_reward: float = 2.0,
        horizon: str = "1H",
        regime_alignment: float = 1.0,
        strategy_edge_multiplier: float = 1.0
    ) -> PathProbabilities:
        """
        Computes calibrated P(TP1), P(TP2), P(TP3), P(SL) honoring conservative path invariants.
        """
        # 1. Base calibrated P(TP1 before SL)
        calibrated_base = self.calibrator.calibrate(raw_win_prob)
        
        # Adjust slightly by market regime alignment and strategy edge
        adjusted_p_tp1 = calibrated_base * (0.90 + (0.10 * regime_alignment)) * (0.95 + (0.05 * strategy_edge_multiplier))
        p_tp1 = max(0.15, min(0.88, adjusted_p_tp1))

        # First invariant: P(TP1 before SL) + P(SL before TP1) = 1.0
        p_sl = round(1.0 - p_tp1, 4)

        # 2. Conditional transition decay to higher targets
        # Reaching TP2 after TP1 depends on momentum continuation (typically 50-70% conditional)
        p_tp2_given_tp1 = max(0.35, min(0.80, 0.65 * (p_tp1 / 0.60)))
        
        # Reaching TP3 after TP2 depends on trend expansion (typically 40-60% conditional)
        p_tp3_given_tp2 = max(0.25, min(0.70, 0.50 * (p_tp1 / 0.60)))

        # Joint probabilities
        p_tp2 = round(p_tp1 * p_tp2_given_tp1, 4)
        p_tp3 = round(p_tp2 * p_tp3_given_tp2, 4)

        return PathProbabilities(
            p_tp1=round(p_tp1, 4),
            p_tp2=p_tp2,
            p_tp3=p_tp3,
            p_sl=p_sl,
            p_tp2_given_tp1=round(p_tp2_given_tp1, 4),
            p_tp3_given_tp2=round(p_tp3_given_tp2, 4),
            risk_reward=round(float(risk_reward), 2),
            is_calibrated=True,
            calibration_method=self.calibrator.method
        )
