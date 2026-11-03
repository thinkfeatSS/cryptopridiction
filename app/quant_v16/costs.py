"""
QUANT EDGE V16: Execution Cost Engine
Specifications:
- Section 20: Cost Engine (Maker/Taker fees, Spread bps, Slippage bps, Funding rates)
- Execution Scenarios: OPTIMISTIC, BASE, CONSERVATIVE, STRESS
- EXT-02: Non-Linear Liquidity Slippage Model (Square-root market impact)
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional
import math

class ExecutionAssumption(str, Enum):
    OPTIMISTIC = "OPTIMISTIC"
    BASE = "BASE"
    CONSERVATIVE = "CONSERVATIVE"
    STRESS = "STRESS"

@dataclass
class CostBreakdown:
    fee_pct: float             # Total round-trip trading fee percentage (e.g. 0.08%)
    spread_pct: float          # Estimated crossing the bid-ask spread (e.g. 0.04%)
    slippage_pct: float        # Expected execution price slippage (e.g. 0.06%)
    funding_pct: float         # Accrued 8h funding drag if holding across funding intervals
    total_cost_pct: float      # Sum of all execution drags
    assumption: ExecutionAssumption
    liquidity_impact_mult: float = 1.0  # EXT-02 non-linear liquidity market impact scalar

class ExecutionCostEngine:
    """
    Computes realistic execution friction to determine whether a trade's gross payoff
    survives actual market microstructures.
    """

    def __init__(
        self,
        spot_maker_fee: float = 0.0004,    # 0.04%
        spot_taker_fee: float = 0.0008,    # 0.08%
        futures_maker_fee: float = 0.0002, # 0.02%
        futures_taker_fee: float = 0.0005, # 0.05%
        default_slippage_bps: float = 6.0  # 6 bps = 0.06%
    ):
        self.spot_maker_fee = spot_maker_fee
        self.spot_taker_fee = spot_taker_fee
        self.futures_maker_fee = futures_maker_fee
        self.futures_taker_fee = futures_taker_fee
        self.default_slippage_bps = default_slippage_bps

    def estimate_costs(
        self,
        market_type: str = "futures",
        observed_spread_bps: float = 4.0,
        historical_slippage_bps: Optional[float] = None,
        est_holding_hours: float = 1.0,
        current_funding_rate: float = 0.0001, # 0.01% per 8h
        assumption: ExecutionAssumption = ExecutionAssumption.BASE,
        position_size_usd: Optional[float] = None,
        volume_24h_usd: Optional[float] = None,
        funding_interval_hours: float = 8.0,
        is_squeeze_transition: bool = False,
    ) -> CostBreakdown:
        """
        Estimates total roundtrip costs under specified scenario.
        Includes EXT-02 non-linear square-root market impact slippage when position size
        and 24h volume are provided.
        """
        if is_squeeze_transition:
            assumption = ExecutionAssumption.STRESS

        is_futures = market_type.lower() in ["futures", "perp", "swap"]
        
        # 1. Base Trading Fees (Roundtrip entry taker + exit taker/maker blended)
        if is_futures:
            taker = self.futures_taker_fee
            maker = self.futures_maker_fee
        else:
            taker = self.spot_taker_fee
            maker = self.spot_maker_fee

        # Entry is usually taker (market/limit chase), exit is 50% limit TP / 50% stop taker
        base_fee_pct = (taker + ((taker + maker) / 2.0)) * 100.0

        # 2. Spread (bps to %)
        spread_bps = max(1.0, observed_spread_bps)
        if is_squeeze_transition and volume_24h_usd is not None and 0 < float(volume_24h_usd) < 25_000_000.0:
            # Low-cap altcoins face sudden order-book depth voids on breakout transitions
            spread_bps = max(spread_bps, 6.0)
        
        # 3. Slippage (bps to %)
        slip_bps = historical_slippage_bps if historical_slippage_bps is not None else self.default_slippage_bps

        # EXT-02: Non-Linear Liquidity Slippage Model
        # Large orders relative to available top-of-book depth experience square-root market impact
        liq_mult = 1.0
        if position_size_usd is not None and volume_24h_usd is not None and float(volume_24h_usd) > 0:
            depth_proxy = max(10000.0, float(volume_24h_usd) * 0.001)  # 0.1% daily volume top-of-book proxy
            impact_ratio = math.sqrt(max(0.0, float(position_size_usd)) / depth_proxy)
            liq_mult = float(max(0.70, min(3.00, impact_ratio)))
            slip_bps = slip_bps * liq_mult

        # Multipliers by execution assumption
        if assumption == ExecutionAssumption.OPTIMISTIC:
            fee_mult = 0.85     # VIP tier / maker rebate
            spread_mult = 0.70
            slip_mult = 0.50
        elif assumption == ExecutionAssumption.BASE:
            fee_mult = 1.00
            spread_mult = 1.00
            slip_mult = 1.00
        elif assumption == ExecutionAssumption.CONSERVATIVE:
            fee_mult = 1.10
            spread_mult = 1.40
            slip_mult = 1.60
        else: # STRESS (e.g. 90th percentile during volatility)
            fee_mult = 1.25
            spread_mult = 2.20
            slip_mult = 2.50

        calc_fee = base_fee_pct * fee_mult
        calc_spread = (spread_bps / 100.0) * spread_mult
        calc_slippage = (slip_bps / 100.0) * slip_mult

        # 4. Funding rate drag (Futures only)
        calc_funding = 0.0
        if is_futures and est_holding_hours > 0:
            # Normalized funding cycle duration (standard 8h cycle, or custom if specified)
            cycle_duration = max(1.0, float(funding_interval_hours))
            funding_cycles = est_holding_hours / cycle_duration
            calc_funding = abs(current_funding_rate * 100.0) * funding_cycles

        fee_pct = round(calc_fee, 4)
        spread_pct = round(calc_spread, 4)
        slippage_pct = round(calc_slippage, 4)
        funding_pct = round(calc_funding, 4)
        total_cost = round(fee_pct + spread_pct + slippage_pct + funding_pct, 4)

        return CostBreakdown(
            fee_pct=fee_pct,
            spread_pct=spread_pct,
            slippage_pct=slippage_pct,
            funding_pct=funding_pct,
            total_cost_pct=total_cost,
            assumption=assumption,
            liquidity_impact_mult=round(liq_mult, 2)
        )
