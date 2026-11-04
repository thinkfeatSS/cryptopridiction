"""
The Only 1 Minute Rectangle Strategy: Crypto Market Execution Filters
Based on Section 14 of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Implements cryptocurrency-specific risk filters:
- Bid/ask spread filter
- Volume confirmation and abnormal candle detection
- Volatility spike guard
- Funding rate friction filter
- Slippage and fee estimation
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig


@dataclass
class MarketFilterResult:
    passed_filters: bool
    rejection_reasons: list
    estimated_fees_pct: float
    estimated_slippage_pct: float
    spread_pct: float
    volume_ratio: float


class CryptoMarketFilter:
    """
    Validates that live cryptocurrency market conditions are safe for execution.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def validate_market_conditions(
        self,
        df_m15: pd.DataFrame,
        current_price: float,
        bid_price: Optional[float] = None,
        ask_price: Optional[float] = None,
        funding_rate: float = 0.0,
        direction: str = "LONG"
    ) -> MarketFilterResult:
        """
        Validates spreads, volume, abnormal candle wicks, and funding rate drag.
        """
        rejection_reasons = []

        # 1. Spread Check
        spread_pct = 0.02 # default 2 bps if bid/ask not provided
        if bid_price is not None and ask_price is not None and bid_price > 0 and ask_price >= bid_price:
            spread_pct = ((ask_price - bid_price) / current_price) * 100.0
            if spread_pct > self.config.max_spread_pct:
                rejection_reasons.append(
                    f"Spread ({spread_pct:.3f}%) exceeds maximum allowable ({self.config.max_spread_pct:.3f}%)"
                )

        # 2. Volume Check
        vol_ratio = 1.0
        if 'volume' in df_m15.columns and len(df_m15) >= 20:
            curr_vol = float(df_m15['volume'].iloc[-1])
            mean_vol = float(df_m15['volume'].rolling(20).mean().iloc[-1])
            vol_ratio = curr_vol / max(1e-8, mean_vol)
            if curr_vol <= 0:
                rejection_reasons.append("Zero trading volume detected on trigger candle")
            elif vol_ratio < 0.15:
                rejection_reasons.append(f"Sub-threshold illiquidity (Volume {vol_ratio:.2f}x of 20MA)")

        # 3. Abnormal Candle Detection (Single candle > 4.5x ATR spike)
        if len(df_m15) >= 15:
            h = df_m15['high']
            l = df_m15['low']
            c = df_m15['close']
            tr = (h - l).iloc[-1]
            atr = (h - l).rolling(14).mean().iloc[-1]
            if tr > (4.5 * max(1e-8, atr)):
                rejection_reasons.append(f"Abnormal volatility spike ({tr/atr:.1f}x ATR) detected")

        # 4. Funding Rate Friction Check
        # If funding rate is extreme against the position (> 0.10% per 8h)
        if direction == "LONG" and funding_rate > self.config.max_funding_rate_pct:
            rejection_reasons.append(f"Prohibitive Long funding rate drag ({funding_rate*100:.3f}% > {self.config.max_funding_rate_pct*100:.3f}%)")
        elif direction == "SHORT" and funding_rate < -self.config.max_funding_rate_pct:
            rejection_reasons.append(f"Prohibitive Short funding rate drag ({funding_rate*100:.3f}% < -{self.config.max_funding_rate_pct*100:.3f}%)")

        total_fee = (self.config.taker_fee_pct * 2.0)
        est_slippage = (self.config.max_slippage_pct * 2.0)

        passed = (len(rejection_reasons) == 0)
        return MarketFilterResult(
            passed_filters=passed,
            rejection_reasons=rejection_reasons,
            estimated_fees_pct=round(total_fee, 4),
            estimated_slippage_pct=round(est_slippage, 4),
            spread_pct=round(spread_pct, 4),
            volume_ratio=round(vol_ratio, 2)
        )

