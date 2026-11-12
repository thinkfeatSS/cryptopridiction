"""
QUANT EDGE V16: Data Validation & Invariant Protection Layer
Specifications:
- Section 3: G1 (Eliminate invalid signals), G2 (Eliminate look-ahead bias)
- Section 13: Data Validation Layer (Price, Direction, Precision)
- Section 14: Data Quality Score (0-100, Gate >= 85)
- Section 15: Look-Ahead Protection (feature_timestamp <= signal_generated_at, violations = 0)
"""

import math
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

def safe_float(val: Any, default: float = 0.0) -> float:
    """
    Defensively parses any numeric or formatted string value into a clean float.
    Handles '+0.00%', '-1.25%', '$45.2', 'None', 'N/A', NaNs, Infs without raising exceptions.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return default
        return float(val)
    s = str(val).strip().replace("%", "").replace("$", "").replace(",", "")
    if s.startswith("+"):
        s = s[1:].strip()
    if not s or s.lower() in ("none", "null", "nan", "n/a", "inf", "-inf"):
        return default
    try:
        f = float(s)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

def safe_ratio(val: Any, default: float = 2.0) -> float:
    """
    Defensively parses Risk:Reward ratios like '1:2.5', '2.5', 2.5 into a clean float.
    Defensively guards against 'inf', 'Infinity', 'nan', zero, or negative ratios.
    Handles terminal risk-free runner formats such as '1:FREE (Runner 1:2.5)' or 'RISK_FREE (LOCKED)'.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val) or val <= 0:
            return default
        return float(val)
    s = str(val).strip()
    if "1:" in s:
        s = s.replace("1:", "").strip()
    if "(" in s:
        import re
        m = re.search(r'(\d+(?:\.\d+)?)', s)
        if m:
            s = m.group(1)
    if any(k in s.lower() for k in ("inf", "infinity", "nan", "free", "locked", "none", "null")):
        return default
    res = safe_float(s, default=default)
    if math.isnan(res) or math.isinf(res) or res <= 0:
        return default
    return res

@dataclass
class ValidationResult:
    is_valid: bool
    rejection_reason: str = ""
    data_quality_score: float = 100.0
    quality_breakdown: Optional[Dict[str, float]] = None
    lookahead_violations: int = 0


class DataValidator:
    """
    Validates physical market pricing invariants and precision before any signal evaluation.
    """
    safe_float = staticmethod(safe_float)
    safe_ratio = staticmethod(safe_ratio)

    @staticmethod
    def validate_price_invariants(
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        tp3: float,
        direction: str
    ) -> Tuple[bool, str]:
        """
        Enforces strict physical market price relations.
        """
        # Positivity check
        if any(p <= 0 or math.isnan(p) or math.isinf(p) for p in [entry, sl, tp1, tp2, tp3]):
            return False, "Non-positive or non-finite price detected (entry/sl/tp <= 0)"

        dir_upper = str(direction).upper()
        if dir_upper in ["LONG", "BULLISH", "BUY"]:
            # Long invariant: SL < Entry < TP1 < TP2 < TP3
            if sl >= entry:
                return False, f"LONG SL ({sl}) must be strictly below Entry ({entry})"
            if tp1 <= entry:
                return False, f"LONG TP1 ({tp1}) must be strictly above Entry ({entry})"
            if tp2 <= tp1:
                return False, f"LONG TP2 ({tp2}) must be strictly above TP1 ({tp1})"
            if tp3 <= tp2:
                return False, f"LONG TP3 ({tp3}) must be strictly above TP2 ({tp2})"

            # Minimum clearance check: Stop and target must not collapse into entry (minimum 0.8% noise protection floor)
            if (entry - sl) / entry < 0.008:
                return False, f"LONG SL distance too tight (< 0.8% of entry: {(entry - sl) / entry * 100:.2f}%)"
            if (tp1 - entry) / entry < 0.008:
                return False, f"LONG TP1 distance too tight (< 0.8% of entry: {(tp1 - entry) / entry * 100:.2f}%)"

        elif dir_upper in ["SHORT", "BEARISH", "SELL"]:
            # Short invariant: SL > Entry > TP1 > TP2 > TP3
            if sl <= entry:
                return False, f"SHORT SL ({sl}) must be strictly above Entry ({entry})"
            if tp1 >= entry:
                return False, f"SHORT TP1 ({tp1}) must be strictly below Entry ({entry})"
            if tp2 >= tp1:
                return False, f"SHORT TP2 ({tp2}) must be strictly below TP1 ({tp1})"
            if tp3 >= tp2:
                return False, f"SHORT TP3 ({tp3}) must be strictly below TP2 ({tp2})"

            if (sl - entry) / entry < 0.008:
                return False, f"SHORT SL distance too tight (< 0.8% of entry: {(sl - entry) / entry * 100:.2f}%)"
            if (entry - tp1) / entry < 0.008:
                return False, f"SHORT TP1 distance too tight (< 0.8% of entry: {(entry - tp1) / entry * 100:.2f}%)"
        else:
            return False, f"Unrecognized trading direction: {direction}"

        return True, ""

    @staticmethod
    def validate_precision(
        entry: float,
        sl: float,
        tick_size: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Ensures rounding does not collapse Entry == SL.
        """
        if abs(entry - sl) < 1e-12:
            return False, "Entry and SL prices are identical (zero stop distance)"

        if tick_size and tick_size > 0:
            if abs(entry - sl) < tick_size:
                return False, f"Stop distance is smaller than minimum exchange tick_size ({tick_size})"

        return True, ""

    @staticmethod
    def validate_probabilities(
        p_tp1: float,
        p_tp2: float,
        p_tp3: float,
        p_sl: float
    ) -> Tuple[bool, str]:
        """
        Validates probability axioms and monotonic decay for multi-target paths:
        1. All probabilities must be finite numbers in [0.0, 1.0].
        2. Monotonic target decay: P(TP3) <= P(TP2) <= P(TP1).
        3. Terminal event coherence: P(TP1) + P(SL) must sum to 1.0 (within numerical tolerance 0.05).
        4. Directional edge: P(TP1) must be >= P(SL) for valid trade candidates.
        """
        probs = [p_tp1, p_tp2, p_tp3, p_sl]
        if any(math.isnan(p) or math.isinf(p) or p < 0.0 or p > 1.0 for p in probs):
            return False, f"Probabilities must be valid finite numbers in [0.0, 1.0]: {probs}"

        # Inverted targets decay check
        if p_tp2 > p_tp1:
            return False, f"Inverted probability: P(TP2) ({p_tp2}) > P(TP1) ({p_tp1})"
        if p_tp3 > p_tp2:
            return False, f"Inverted probability: P(TP3) ({p_tp3}) > P(TP2) ({p_tp2})"

        # Coherence check
        if abs((p_tp1 + p_sl) - 1.0) > 0.05:
            return False, f"Terminal probability coherence violation: P(TP1) + P(SL) = {p_tp1 + p_sl:.4f} != 1.0"

        # Edge check
        if p_sl > p_tp1:
            return False, f"Inverted probability edge: P(SL) ({p_sl:.4f}) > P(TP1) ({p_tp1:.4f})"

        return True, ""


class LookaheadGuard:
    """
    Guarantees no future information leaks into feature calculation or signal generation.
    Invariant: feature_timestamp <= signal_generated_at
    """

    def __init__(self):
        self.lookahead_violations: int = 0

    def check_timestamps(
        self,
        signal_generated_at: datetime,
        feature_timestamps: Dict[str, datetime]
    ) -> Tuple[bool, int, List[str]]:
        """
        Checks feature timestamps against signal creation time.
        """
        violations = []
        if signal_generated_at.tzinfo is None:
            signal_generated_at = signal_generated_at.replace(tzinfo=timezone.utc)

        for feat_name, ts in feature_timestamps.items():
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            # Invariant: feature time must be <= signal generation time
            if ts > signal_generated_at:
                violations.append(f"{feat_name} timestamp ({ts.isoformat()}) > signal generation ({signal_generated_at.isoformat()})")

        count = len(violations)
        self.lookahead_violations += count
        is_clean = count == 0
        return is_clean, count, violations


class DataQualityScorer:
    """
    Computes Section 14 Data Quality Score (0 - 100).
    Minimum Threshold: DATA_QUALITY >= 85.
    
    Components:
    - Market data freshness       20
    - OHLC completeness           15
    - Order-book quality          15
    - Price precision             10
    - Feature completeness        15
    - Timestamp integrity         15
    - Exchange metadata           10
    """

    @staticmethod
    def evaluate(
        data_age_seconds: float,
        ohlc_complete: bool = True,
        orderbook_depth_ok: bool = True,
        precision_valid: bool = True,
        feature_missing_count: int = 0,
        total_feature_count: int = 30,
        timestamp_valid: bool = True,
        exchange_metadata_ok: bool = True
    ) -> Tuple[float, Dict[str, float]]:
        
        breakdown = {}

        # 1. Freshness (20 pts)
        if data_age_seconds <= 15.0:
            freshness_pts = 20.0
        elif data_age_seconds <= 60.0:
            freshness_pts = 16.0
        elif data_age_seconds <= 180.0:
            freshness_pts = 10.0
        elif data_age_seconds <= 300.0:
            freshness_pts = 5.0
        else:
            freshness_pts = 0.0
        breakdown["data_freshness"] = freshness_pts

        # 2. OHLC Completeness (15 pts)
        breakdown["ohlc_completeness"] = 15.0 if ohlc_complete else 0.0

        # 3. Order-book quality (15 pts)
        breakdown["orderbook_quality"] = 15.0 if orderbook_depth_ok else 5.0

        # 4. Price Precision (10 pts)
        breakdown["price_precision"] = 10.0 if precision_valid else 0.0

        # 5. Feature Completeness (15 pts)
        if total_feature_count > 0:
            feat_ratio = max(0.0, 1.0 - (feature_missing_count / total_feature_count))
            breakdown["feature_completeness"] = round(15.0 * feat_ratio, 2)
        else:
            breakdown["feature_completeness"] = 15.0

        # 6. Timestamp integrity (15 pts)
        breakdown["timestamp_integrity"] = 15.0 if timestamp_valid else 0.0

        # 7. Exchange metadata (10 pts)
        breakdown["exchange_metadata"] = 10.0 if exchange_metadata_ok else 0.0

        total_score = round(sum(breakdown.values()), 2)
        return total_score, breakdown
