"""
The Only 1 Minute Rectangle Strategy: 100-Point Signal Quality Scoring Engine
Based on Section 12 of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Implements an explainable 100-point multi-factor model:
Component                            Maximum Score
1. EMA Trend Alignment               15
2. Market Structure Confirmation     15
3. Valid Liquidity Sweep             20
4. Wick Rejection Strength           10
5. M15 Weakness Confirmation         15
6. FVG / Imbalance Confluence        10
7. Session High/Low Confluence       5
8. M1 Rectangle Flip Confirmation    10
Total:                               100

Scoring Rules:
- 85-100: High-quality signal
- 75-84:  Valid signal
- Below 75: Reject (Minimum default score: 75)

Mandatory Gates: If ANY mandatory condition fails, trade is rejected regardless of score.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig


@dataclass
class ScoreBreakdown:
    ema_trend_score: float = 0.0          # max 15
    market_structure_score: float = 0.0   # max 15
    liquidity_sweep_score: float = 0.0    # max 20
    wick_rejection_score: float = 0.0     # max 10
    weakness_confirm_score: float = 0.0   # max 15
    fvg_confluence_score: float = 0.0     # max 10
    session_confluence_score: float = 0.0 # max 5
    m1_flip_score: float = 0.0            # max 10
    total_score: float = 0.0              # max 100
    grade: str = "REJECTED"               # "HIGH_QUALITY", "VALID", or "REJECTED"
    mandatory_gates_passed: bool = False
    failed_mandatory_gates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ema_trend_score": round(self.ema_trend_score, 1),
            "market_structure_score": round(self.market_structure_score, 1),
            "liquidity_sweep_score": round(self.liquidity_sweep_score, 1),
            "wick_rejection_score": round(self.wick_rejection_score, 1),
            "weakness_confirm_score": round(self.weakness_confirm_score, 1),
            "fvg_confluence_score": round(self.fvg_confluence_score, 1),
            "session_confluence_score": round(self.session_confluence_score, 1),
            "m1_flip_score": round(self.m1_flip_score, 1),
            "total_score": round(self.total_score, 1),
            "grade": self.grade,
            "mandatory_gates_passed": self.mandatory_gates_passed,
            "failed_mandatory_gates": self.failed_mandatory_gates
        }


class SignalScorer:
    """
    Computes explainable 100-point signal score and enforces non-negotiable mandatory gates.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def evaluate_score(
        self,
        ema_score: float,
        structure_score: float,
        sweep_score: float,
        wick_score: float,
        weakness_score: float,
        fvg_score: float,
        session_score: float,
        m1_flip_score: float,
        # Mandatory condition flags
        has_valid_trend: bool,
        has_valid_structure: bool,
        has_valid_sweep: bool,
        has_confirmed_weakness: bool,
        has_valid_rectangle: bool,
        has_confirmed_m1_flip: bool,
        has_valid_sl: bool,
        has_min_rr: bool
    ) -> ScoreBreakdown:
        """
        Synthesizes scores and validates mandatory conditions.
        """
        failed_gates = []
        if not has_valid_trend:
            failed_gates.append("Valid trend direction failed")
        if not has_valid_structure:
            failed_gates.append("Valid M15 structure failed")
        if not has_valid_sweep:
            failed_gates.append("Valid liquidity sweep failed")
        if not has_confirmed_weakness:
            failed_gates.append("Confirmed weakness failed")
        if not has_valid_rectangle:
            failed_gates.append("Valid rectangle failed")
        if not has_confirmed_m1_flip:
            failed_gates.append("Confirmed M1 flip failed")
        if not has_valid_sl:
            failed_gates.append("Valid Stop Loss failed")
        if not has_min_rr:
            failed_gates.append("Minimum Risk-to-Reward ratio failed")

        all_gates_passed = (len(failed_gates) == 0)

        # Cap individual components to their defined maximums
        ema_pts = min(15.0, max(0.0, ema_score))
        struct_pts = min(15.0, max(0.0, structure_score))
        sweep_pts = min(20.0, max(0.0, sweep_score))
        wick_pts = min(10.0, max(0.0, wick_score))
        weak_pts = min(15.0, max(0.0, weakness_score))
        fvg_pts = min(10.0, max(0.0, fvg_score))
        sess_pts = min(5.0, max(0.0, session_score))
        flip_pts = min(10.0, max(0.0, m1_flip_score))

        total = ema_pts + struct_pts + sweep_pts + wick_pts + weak_pts + fvg_pts + sess_pts + flip_pts
        total = round(min(100.0, max(0.0, total)), 1)

        grade = "REJECTED"
        if all_gates_passed:
            if total >= self.config.high_quality_score:
                grade = "HIGH_QUALITY"
            elif total >= self.config.min_signal_score:
                grade = "VALID"
            else:
                grade = "REJECTED"
        else:
            grade = "REJECTED"

        return ScoreBreakdown(
            ema_trend_score=ema_pts,
            market_structure_score=struct_pts,
            liquidity_sweep_score=sweep_pts,
            wick_rejection_score=wick_pts,
            weakness_confirm_score=weak_pts,
            fvg_confluence_score=fvg_pts,
            session_confluence_score=sess_pts,
            m1_flip_score=flip_pts,
            total_score=total,
            grade=grade,
            mandatory_gates_passed=all_gates_passed,
            failed_mandatory_gates=failed_gates
        )
