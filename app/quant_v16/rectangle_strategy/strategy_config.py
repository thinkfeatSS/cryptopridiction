"""
The Only 1 Minute Rectangle Strategy: Configuration Engine
Based on "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Provides dynamic, non-hardcoded configuration for:
- Trend filters (EMA 50, EMA 200, Both)
- Market structure and pivot lookback
- Liquidity sweep & wick rejection thresholds
- Dynamic rectangle dimensions & lifecycle
- M1 flip confirmation modes (Safe vs. Aggressive)
- Risk management (Dynamic SL buffer, Take Profit RR scaling)
- 100-point signal scoring and session filters
- Crypto-specific execution and friction models
"""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from enum import Enum


class EmaFilterType(str, Enum):
    EMA_50 = "EMA_50"
    EMA_200 = "EMA_200"
    BOTH = "BOTH"


class EntryMode(str, Enum):
    SAFE = "SAFE"            # Mode A: Requires confirmed M1 candle close outside rectangle (Default)
    AGGRESSIVE = "AGGRESSIVE"# Mode B: Allows entry inside rectangle on key-level rejection (Disabled by default)


class FvgFilterMode(str, Enum):
    RELAXED = "RELAXED"      # FVG provides confluence bonus points (Default)
    STRICT = "STRICT"        # FVG is mandatory requirement


@dataclass
class RectangleStrategyConfig:
    # 1. Strategy Identification
    strategy_name: str = "The Only 1 Minute Rectangle Strategy"
    strategy_id: str = "THE_ONLY_1_MINUTE_RECTANGLE_STRATEGY"
    enabled: bool = True
    default_exchange: str = "BINANCE"
    default_market: str = "Binance USDT-M Futures"
    supported_pairs: List[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"
    ])

    # 2. Timeframes
    timeframe_analysis: str = "15m"  # Primary market structure, sweep, weakness, rectangle
    entry_timeframe: str = "1m"      # Precise execution and rectangle flip timeframe

    # 3. EMA Market Direction Configuration
    ema_type: EmaFilterType = EmaFilterType.BOTH
    ema_fast_period: int = 50
    ema_slow_period: int = 200
    ema_slope_lookback: int = 5
    ema_proximity_atr_mult: float = 0.15  # Avoid chop directly glued to EMA line
    ranging_adx_threshold: float = 20.0   # ADX below 20 indicates sideways ranging chop
    ranging_atr_compression_mult: float = 0.65 # ATR / ATR_MA20 < 0.65 indicates severe compression

    # 4. Market Structure Engine
    swing_pivot_left_bars: int = 3   # Left lookback for swing vertex confirmation
    swing_pivot_right_bars: int = 2  # Right lookback: confirmed pivot requires 2 closed candles
    structure_lookback_bars: int = 40# Window for finding active swing highs and lows

    # 5. Liquidity Sweep Detection
    min_sweep_atr_mult: float = 0.05 # Minimum depth of sweep past swing level (in ATR)
    max_sweep_atr_mult: float = 2.50 # Maximum sweep depth before classified as runaway breakout
    min_wick_to_body_ratio: float = 0.60 # Lower wick / Body (Longs) or Upper wick / Body (Shorts)
    min_rejection_wick_pct: float = 0.25 # Rejection wick must be at least 25% of total candle range

    # 6. Fair Value Gap (FVG) and Imbalance Analysis
    fvg_mode: FvgFilterMode = FvgFilterMode.RELAXED
    fvg_lookback_bars: int = 15
    fvg_min_size_atr: float = 0.10

    # 7. Dynamic Rectangle Generation
    rectangle_expiry_m1_bars: int = 60 # Expiration window: 60 M1 bars (1 hour) to trigger flip
    min_rectangle_height_atr: float = 0.10
    max_rectangle_height_atr: float = 3.00

    # 8. M1 Entry Engine
    entry_mode: EntryMode = EntryMode.SAFE # Mode A: Safe entry is mandatory default
    require_retest_before_flip: bool = False # Whether price must re-enter rectangle before flip
    max_entry_delay_m1_bars: int = 15 # Maximum M1 candles allowed after initial flip close

    # 9. Stop Loss & Take Profit Engine
    sl_buffer_atr_mult: float = 0.15   # Buffer beyond rectangle boundary / sweep extreme
    min_risk_reward: float = 2.0       # Minimum default R:R ratio (1:2)
    target_risk_rewards: List[float] = field(default_factory=lambda: [2.0, 2.5, 3.0, 4.0])
    use_structural_targets: bool = True # Use next M15 swing target when it meets min RR
    min_sl_pct: float = 0.15           # Minimum SL distance (protect against zero/micro SL)
    max_sl_pct: float = 3.50           # Maximum SL distance (reject oversized stops)

    # 10. Signal Scoring Engine (100-Point Model)
    min_signal_score: float = 75.0     # Minimum score for a valid signal
    high_quality_score: float = 85.0   # Score for grade A+ / prime signal

    # 11. Session High / Low Filter
    session_confluence_enabled: bool = True
    asian_session_utc: tuple = (0, 8)   # 00:00 - 08:00 UTC
    london_session_utc: tuple = (8, 16) # 08:00 - 16:00 UTC
    ny_session_utc: tuple = (13, 21)    # 13:00 - 21:00 UTC

    # 12. Crypto Execution & Friction Modeling
    max_spread_pct: float = 0.08       # Maximum allowable spread (8 bps)
    max_slippage_pct: float = 0.05     # Estimated slippage per leg
    maker_fee_pct: float = 0.02        # Maker fee (2 bps)
    taker_fee_pct: float = 0.05        # Taker fee (5 bps)
    max_funding_rate_pct: float = 0.10 # 0.10% per 8h funding cap

    # 13. Operational & Anti-Repaint Controls
    signal_cooldown_bars: int = 5      # M15 bars between duplicate setups on same symbol
    paper_trading_min_sample: int = 10 # Required paper trades before production activation

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["ema_type"] = self.ema_type.value
        d["entry_mode"] = self.entry_mode.value
        d["fvg_mode"] = self.fvg_mode.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RectangleStrategyConfig":
        cfg = cls()
        for k, v in d.items():
            if hasattr(cfg, k):
                if k == "ema_type" and isinstance(v, str):
                    setattr(cfg, k, EmaFilterType(v))
                elif k == "entry_mode" and isinstance(v, str):
                    setattr(cfg, k, EntryMode(v))
                elif k == "fvg_mode" and isinstance(v, str):
                    setattr(cfg, k, FvgFilterMode(v))
                else:
                    setattr(cfg, k, v)
        return cfg

    @classmethod
    def load_from_env_or_file(cls, filepath: Optional[str] = None) -> "RectangleStrategyConfig":
        """Loads configuration from JSON file or environment variables dynamically."""
        cfg = cls()
        target_path = filepath or os.getenv("RECTANGLE_STRATEGY_CONFIG_PATH")
        if target_path and os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return cls.from_dict(data)
            except Exception as e:
                print(f"[RECTANGLE STRATEGY CONFIG] Error reading {target_path}: {e}")

        # Override via environment variables if provided
        if os.getenv("RECTANGLE_STRATEGY_ENABLED") is not None:
            cfg.enabled = os.getenv("RECTANGLE_STRATEGY_ENABLED", "true").lower() in ("1", "true", "yes")
        if os.getenv("RECTANGLE_EMA_TYPE") in ("EMA_50", "EMA_200", "BOTH"):
            cfg.ema_type = EmaFilterType(os.getenv("RECTANGLE_EMA_TYPE"))
        if os.getenv("RECTANGLE_ENTRY_MODE") in ("SAFE", "AGGRESSIVE"):
            cfg.entry_mode = EntryMode(os.getenv("RECTANGLE_ENTRY_MODE"))
        if os.getenv("RECTANGLE_MIN_RR"):
            try:
                cfg.min_risk_reward = float(os.getenv("RECTANGLE_MIN_RR"))
            except ValueError:
                pass
        if os.getenv("RECTANGLE_MIN_SCORE"):
            try:
                cfg.min_signal_score = float(os.getenv("RECTANGLE_MIN_SCORE"))
            except ValueError:
                pass

        return cfg

