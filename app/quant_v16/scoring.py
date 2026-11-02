"""
QUANT EDGE V16: Signal Scoring & Composite Grade Engine
Specifications:
- Section 23: V16 Signal Score:
    25% * Probability Quality
    15% * Expected Net Return
    10% * Regime Alignment
    10% * Strategy Historical Edge
    10% * Risk/Reward
    10% * Liquidity
    05% * Volume Confirmation
    05% * Higher-Timeframe Alignment
    05% * Execution Quality
    05% * Data Quality
- Section 24: Grade System (A+, A, B, WATCH, NO TRADE)
"""

from enum import Enum
from typing import Dict, Any, Tuple
from dataclasses import dataclass

class SignalGrade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    WATCH = "WATCH"
    NO_TRADE = "NO_TRADE"

class SignalStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    WATCHLIST = "WATCHLIST"
    REJECTED = "REJECTED"

@dataclass
class SignalScoreBreakdown:
    total_score: float              # 0 - 100
    prob_quality_pts: float         # Max 25
    net_ev_pts: float               # Max 15
    regime_alignment_pts: float     # Max 10
    strategy_edge_pts: float        # Max 10
    risk_reward_pts: float          # Max 10
    liquidity_pts: float            # Max 10
    volume_pts: float               # Max 5
    htf_alignment_pts: float        # Max 5
    execution_quality_pts: float    # Max 5
    data_quality_pts: float         # Max 5
    grade: SignalGrade
    status: SignalStatus
    rejection_reasons: str = ""

class V16SignalScorer:
    """
    Ranks qualified signals using multi-factor normalized scoring and enforces strict institutional grading hurdles.
    """

    @classmethod
    def evaluate(cls, *args, **kwargs):
        return cls.calculate_score_and_grade(*args, **kwargs)

    @staticmethod
    def calculate_score_and_grade(
        p_tp1: float,                     # Calibrated P(TP1), e.g. 0.714
        expected_net_return_pct: float,   # Net EV %, e.g. 0.86%
        regime_alignment: float,          # 0.0 to 1.0
        strategy_pf: float,               # Strategy historical profit factor, e.g. 1.35
        rolling_50_pf: float,             # Rolling 50 PF
        risk_reward: float,               # e.g. 1.86
        liquidity_score: float,           # 0 - 100
        volume_confirmation: bool,        # True/False
        htf_aligned: bool,                # Higher timeframe aligned
        data_quality_score: float,        # 0 - 100
        execution_quality_score: float = 90.0,
        strategy_disabled: bool = False,
        thesis_exposure_exceeded: bool = False,
        has_lookahead_violation: bool = False
    ) -> SignalScoreBreakdown:
        
        # Hard Rejection Gate: Any critical failure defaults immediately to NO_TRADE
        rejections = []
        if has_lookahead_violation:
            rejections.append("Lookahead timestamp violation detected")
        if data_quality_score < 85.0:
            rejections.append(f"Data quality score below 85 gate ({data_quality_score:.1f})")
        if expected_net_return_pct <= 0.0:
            rejections.append(f"Expected Net Return is non-positive ({expected_net_return_pct:+.2f}%)")
        if strategy_disabled:
            rejections.append("Strategy archetype is paused or disabled")
        if thesis_exposure_exceeded:
            rejections.append("Thesis exposure limit reached (max 1 position)")
        if liquidity_score < 40.0:
            rejections.append("Liquidity score below minimum 40.0 trade threshold")

        # 1. Probability Quality (25% weight): P(TP1) normalized
        prob_quality_pts = round(min(25.0, max(0.0, (p_tp1 - 0.40) * (25.0 / 0.40))), 2)

        # 2. Expected Net Return (15% weight): e.g. 1.5% Net EV = full 15 pts
        net_ev_pts = round(min(15.0, max(0.0, (expected_net_return_pct / 1.50) * 15.0)), 2)

        # 3. Regime Alignment (10% weight)
        regime_alignment_pts = round(min(10.0, max(0.0, regime_alignment * 10.0)), 2)

        # 4. Strategy Historical Edge (10% weight): PF 1.0 to 1.6
        strategy_edge_pts = round(min(10.0, max(0.0, (strategy_pf - 1.0) * (10.0 / 0.60))), 2)

        # 5. Risk / Reward (10% weight): RR 1.0 to 3.0
        risk_reward_pts = round(min(10.0, max(0.0, (risk_reward - 1.0) * (10.0 / 2.0))), 2)

        # 6. Liquidity Score (10% weight)
        liquidity_pts = round(min(10.0, max(0.0, (liquidity_score / 100.0) * 10.0)), 2)

        # 7. Volume Confirmation (5% weight)
        volume_pts = 5.0 if volume_confirmation else 1.5

        # 8. HTF Alignment (5% weight)
        htf_alignment_pts = 5.0 if htf_aligned else 1.0

        # 9. Execution Quality (5% weight)
        execution_quality_pts = round(min(5.0, max(0.0, (execution_quality_score / 100.0) * 5.0)), 2)

        # 10. Data Quality (5% weight)
        data_quality_pts = round(min(5.0, max(0.0, (data_quality_score / 100.0) * 5.0)), 2)

        total_score = round(
            prob_quality_pts + net_ev_pts + regime_alignment_pts + strategy_edge_pts +
            risk_reward_pts + liquidity_pts + volume_pts + htf_alignment_pts +
            execution_quality_pts + data_quality_pts, 2
        )

        # Grade Determination matching Section 24
        if rejections:
            grade = SignalGrade.NO_TRADE
            status = SignalStatus.REJECTED
        else:
            # A+ Grade Requirements:
            # Score >= 85, Net EV >= 1.00%, P(TP1) >= 65%, Strategy PF >= 1.30, Rolling PF >= 1.10, Data Quality >= 90
            is_a_plus = (
                total_score >= 85.0 and
                expected_net_return_pct >= 1.00 and
                p_tp1 >= 0.65 and
                strategy_pf >= 1.30 and
                rolling_50_pf >= 1.10 and
                data_quality_score >= 90.0 and
                liquidity_score >= 80.0
            )

            # A Grade Requirements:
            # Score >= 75, Net EV >= 0.50%, P(TP1) >= 60%, Strategy PF >= 1.15, Data Quality >= 85
            is_a = (
                total_score >= 75.0 and
                expected_net_return_pct >= 0.50 and
                p_tp1 >= 0.60 and
                strategy_pf >= 1.15 and
                data_quality_score >= 85.0 and
                liquidity_score >= 60.0
            )

            # B Grade Requirements:
            # Score >= 65, Net EV >= 0.25%
            is_b = (total_score >= 65.0 and expected_net_return_pct >= 0.25)

            if is_a_plus:
                grade = SignalGrade.A_PLUS
                status = SignalStatus.QUALIFIED
            elif is_a:
                grade = SignalGrade.A
                status = SignalStatus.QUALIFIED
            elif is_b:
                grade = SignalGrade.B
                status = SignalStatus.WATCHLIST
            elif expected_net_return_pct > 0.0:
                grade = SignalGrade.WATCH
                status = SignalStatus.WATCHLIST
            else:
                grade = SignalGrade.NO_TRADE
                status = SignalStatus.REJECTED

        return SignalScoreBreakdown(
            total_score=total_score,
            prob_quality_pts=prob_quality_pts,
            net_ev_pts=net_ev_pts,
            regime_alignment_pts=regime_alignment_pts,
            strategy_edge_pts=strategy_edge_pts,
            risk_reward_pts=risk_reward_pts,
            liquidity_pts=liquidity_pts,
            volume_pts=volume_pts,
            htf_alignment_pts=htf_alignment_pts,
            execution_quality_pts=execution_quality_pts,
            data_quality_pts=data_quality_pts,
            grade=grade,
            status=status,
            rejection_reasons="; ".join(rejections)
        )
