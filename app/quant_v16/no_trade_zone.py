"""
QUANT EDGE V16: Institutional No Trade Zone (NTZ) & Dead Market Filter
Specifications:
- Section 1: Consolidation & Chop Protection (CHOP >= 61.8, ADX < 20, BBW Squeeze)
- Section 2: Low Volume & Illiquidity Filter (RVOL < 0.60x, 24h Quote Vol < $2.0M)
- Section 3: Mid-Range Exclusion (Middle 40%-60% of Bollinger Bands in non-trending regimes)
- Section 4: Lack of Confirmation (Wick fakeouts, Order Blocks hovering >1.5 ATRs away without mitigation)
- Section 5: Macro & Event Blackout (BTC flash dump cascade, pre-event news blackout, extreme funding crowding)
"""

from enum import Enum
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class NoTradeZoneReason(str, Enum):
    CLEAR = "CLEAR"
    CHOP_CONSOLIDATION = "CHOP_CONSOLIDATION"
    DRY_VOLUME_ILLIQUID = "DRY_VOLUME_ILLIQUID"
    MID_RANGE_CHOP = "MID_RANGE_CHOP"
    UNCONFIRMED_WICK_FAKEOUT = "UNCONFIRMED_WICK_FAKEOUT"
    UNCONFIRMED_OB_MID_AIR = "UNCONFIRMED_OB_MID_AIR"
    MACRO_BTC_CASCADE = "MACRO_BTC_CASCADE"
    PRE_EVENT_BLACKOUT = "PRE_EVENT_BLACKOUT"
    EXTREME_FUNDING_CROWD = "EXTREME_FUNDING_CROWD"
    DEAD_ZONE_ALIGNMENT = "DEAD_ZONE_ALIGNMENT"
    STALE_PRICE_FEED = "STALE_PRICE_FEED"


class NoTradeZoneEngine:
    """
    Evaluates micro and macro parameters to detect dead, dangerous, or unconfirmed market conditions.
    When active, prevents signal generation, blocks WhatsApp dispatch, and halts paper trade entries.
    """

    @staticmethod
    def compute_chop_index(df: pd.DataFrame, period: int = 14) -> float:
        """Calculates Choppiness Index (0-100). >61.8 indicates severe sideways chop."""
        if df is None or len(df) < period + 1:
            return 50.0
        try:
            high_col = df['high']
            low_col = df['low']
            close_col = df['close']

            # True Range
            tr1 = high_col - low_col
            tr2 = (high_col - close_col.shift(1)).abs()
            tr3 = (low_col - close_col.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            atr_sum = tr.rolling(period).sum()
            high_max = high_col.rolling(period).max()
            low_min = low_col.rolling(period).min()
            denom = high_max - low_min

            chop = 100.0 * (np.log10(atr_sum / (denom + 1e-10)) / np.log10(period))
            val = float(chop.iloc[-1])
            if np.isnan(val) or np.isinf(val):
                return 50.0
            return max(0.0, min(100.0, val))
        except Exception:
            return 50.0

    @staticmethod
    def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
        """Calculates standard Welles Wilder ADX (0-100). <20 indicates absence of trend."""
        if df is None or len(df) < period * 2:
            return 20.0
        try:
            high = df['high']
            low = df['low']
            close = df['close']

            up_move = high - high.shift(1)
            down_move = low.shift(1) - low

            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            tr_smooth = tr.ewm(alpha=1.0 / period, adjust=False).mean()
            plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / (tr_smooth + 1e-10)
            minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / (tr_smooth + 1e-10)

            dx = 100.0 * (plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-10)
            adx_series = dx.ewm(alpha=1.0 / period, adjust=False).mean()
            val = float(adx_series.iloc[-1])
            if np.isnan(val) or np.isinf(val):
                return 20.0
            return max(0.0, min(100.0, val))
        except Exception:
            return 20.0

    @staticmethod
    def compute_rvol(df: pd.DataFrame, period: int = 20) -> float:
        """Calculates Relative Volume (Current Bar Volume vs 20-period Moving Average)."""
        if df is None or len(df) < 5 or 'volume' not in df.columns:
            return 1.0
        try:
            vol = df['volume']
            vol_now = float(vol.iloc[-1])
            vol_ma = float(vol.rolling(period, min_periods=3).mean().iloc[-1])
            if vol_ma <= 0.0:
                return 1.0
            return round(vol_now / vol_ma, 2)
        except Exception:
            return 1.0

    @staticmethod
    def compute_bollinger_range_position(df: pd.DataFrame, period: int = 20, nb_dev: float = 2.0) -> tuple:
        """
        Returns (range_pos_pct, bbw_pct):
        - range_pos_pct: (close - lower) / (upper - lower) * 100. (50% is exact midline)
        - bbw_pct: (upper - lower) / middle * 100. (<1.5% indicates tight compression)
        """
        if df is None or len(df) < period or 'close' not in df.columns:
            return 50.0, 3.0
        try:
            close = df['close']
            mid = float(close.rolling(period).mean().iloc[-1])
            std = float(close.rolling(period).std().iloc[-1])
            upper = mid + (std * nb_dev)
            lower = mid - (std * nb_dev)
            c_now = float(close.iloc[-1])

            width = upper - lower
            if width <= 0 or mid <= 0:
                return 50.0, 3.0

            pos_pct = max(0.0, min(100.0, ((c_now - lower) / width) * 100.0))
            bbw_pct = (width / mid) * 100.0
            return round(pos_pct, 1), round(bbw_pct, 2)
        except Exception:
            return 50.0, 3.0

    def evaluate_asset_ntz(
        self,
        df: pd.DataFrame,
        current_price: float,
        anchor_tf: str = "1h",
        btc_shield_info: Optional[Dict[str, Any]] = None,
        funding_info: Optional[Dict[str, Any]] = None,
        stats_24h: Optional[Dict[str, Any]] = None,
        fund_matrix: Optional[Dict[str, Any]] = None,
        ob_setup: Optional[Dict[str, Any]] = None,
        alignment_score: float = 0.0,
        meta_win_prob: float = 0.50,
        direction: str = "LONG",
        decision: str = ""
    ) -> Dict[str, Any]:
        """
        Comprehensive multi-factor NTZ check.
        Returns detailed status, code, user-friendly badge, and triggered reasons.
        """
        reasons: List[str] = []
        primary_code = NoTradeZoneReason.CLEAR
        primary_label = ""
        badge = ""

        # 1. Indicator Calculations
        chop = self.compute_chop_index(df, period=14)
        adx = self.compute_adx(df, period=14)
        rvol = self.compute_rvol(df, period=20)
        range_pos, bbw = self.compute_bollinger_range_position(df, period=20)

        # 2. Candle Wick Anatomy (Check for Wick Fakeouts on completed candle iloc[-2])
        upper_wick_ratio = 0.0
        lower_wick_ratio = 0.0
        is_red_candle = False
        is_green_candle = False
        has_cleared_rejection = False
        has_cleared_absorption = False
        if df is not None and len(df) >= 3:
            try:
                c_now = float(df['close'].iloc[-1])
                c_comp = float(df['close'].iloc[-2])
                o_comp = float(df['open'].iloc[-2])
                h_comp = float(df['high'].iloc[-2])
                l_comp = float(df['low'].iloc[-2])
                bar_rng = max(1e-8, h_comp - l_comp)
                upper_wick_ratio = (h_comp - max(c_comp, o_comp)) / bar_rng
                lower_wick_ratio = (min(c_comp, o_comp) - l_comp) / bar_rng
                is_red_candle = c_comp < o_comp
                is_green_candle = c_comp > o_comp
                has_cleared_rejection = (c_now > h_comp)
                has_cleared_absorption = (c_now < l_comp)
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # TIMEFRAME-SPECIFIC THRESHOLD PARAMETERIZATION (15M, 1H, 4H, 24H)
        # ----------------------------------------------------------------------
        tf_clean = str(anchor_tf or "1h").lower()
        if "15" in tf_clean:
            chop_severe_thresh = 61.8
            adx_severe_thresh = 20.0
            chop_squeeze_thresh = 58.0
            adx_squeeze_thresh = 18.0
            bbw_squeeze_thresh = 1.40
            rvol_dry_thresh = 0.60
            min_quote_vol = 2000000.0  # $2M
            tf_label = "15M"
        elif "1h" in tf_clean or "30m" in tf_clean or "intraday" in tf_clean:
            chop_severe_thresh = 60.0
            adx_severe_thresh = 20.0
            chop_squeeze_thresh = 56.0
            adx_squeeze_thresh = 18.0
            bbw_squeeze_thresh = 1.80
            rvol_dry_thresh = 0.65
            min_quote_vol = 2000000.0  # $2M
            tf_label = "1H"
        elif "4h" in tf_clean or "swing" in tf_clean:
            chop_severe_thresh = 58.0
            adx_severe_thresh = 22.0
            chop_squeeze_thresh = 54.0
            adx_squeeze_thresh = 19.0
            bbw_squeeze_thresh = 2.50
            rvol_dry_thresh = 0.70
            min_quote_vol = 3000000.0  # $3M
            tf_label = "4H"
        else:  # 24h, 1d, macro
            chop_severe_thresh = 56.0
            adx_severe_thresh = 22.0
            chop_squeeze_thresh = 52.0
            adx_squeeze_thresh = 20.0
            bbw_squeeze_thresh = 3.50
            rvol_dry_thresh = 0.75
            min_quote_vol = 5000000.0  # $5M
            tf_label = "24H"

        # ----------------------------------------------------------------------
        # PILLAR 0: MARKET DATA FRESHNESS ENFORCEMENT (15s Max Age Constraint)
        # ----------------------------------------------------------------------
        live_price_age = float(df.attrs.get("live_price_freshness_seconds", 0.0)) if (df is not None and hasattr(df, "attrs")) else 0.0
        is_price_fresh = bool(df.attrs.get("is_price_fresh_15s", True)) if (df is not None and hasattr(df, "attrs")) else True
        if (live_price_age > 15.0 or not is_price_fresh) and (live_price_age > 0.0):
            reasons.append(f"Stale Price Feed: ticker age ({live_price_age:.1f}s) exceeds 15.0s maximum limit. Rate-limiting recovery active; locking NTZ.")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.STALE_PRICE_FEED
                primary_label = f"🛑 NO TRADE ZONE (STALE PRICE FEED > 15s)"
                badge = f"STALE-FEED ({live_price_age:.0f}s)"

        # ----------------------------------------------------------------------
        # PILLAR 1: CONSOLIDATION & CHOPPINESS (Dead sideways drift per timeframe)
        # ----------------------------------------------------------------------
        # Institutional Exemption: Order block touches, Range rotations, Liquidity sweeps, FVG retests, VWAP bounces, and Squeeze Expansions
        # actively trade structural reaction levels with positive edge and should not be suppressed as generic chop.
        has_fresh_ob = bool(ob_setup and ob_setup.get("setup_detected"))
        exempt_strategies = [
            "BREAKOUT", "EXPANSION", "ORDER_BLOCK", "BREAKER",
            "RANGE_BOUNCE", "RANGE_ROTATION", "RANGE_SUPPORT", "RANGE_RESISTANCE",
            "SUB_RANGE", "MEAN_REVERSION", "SWEEP", "RECLAIM", "FVG", "VWAP",
            "DIP_BUY", "RALLY_FADE", "COILING", "TURTLE_SOUP", "INSIDE_BAR", "SQUEEZE"
        ]
        decision_str = str(decision).upper() if decision else ""
        is_exempt_strategy = has_fresh_ob or any(k in decision_str for k in exempt_strategies)

        # Condition A: Severe Chop combined with non-trending ADX on this timeframe (exempting institutional setups)
        is_severe_chop = ((not is_exempt_strategy) and chop >= chop_severe_thresh and adx < adx_severe_thresh)
        # Condition B: High Chop + weak ADX + tight BBW squeeze without institutional setup/expansion
        is_coiled_squeeze = ((not is_exempt_strategy) and chop >= chop_squeeze_thresh and adx < adx_squeeze_thresh and bbw < bbw_squeeze_thresh)

        # Condition C: Middle 50% Range Box Chop (25% < range_pos < 75%) with non-trending ADX (exempting institutional setups)
        is_middle_chop = (
            (not is_exempt_strategy)
            and (25.0 < range_pos < 75.0)
            and (adx < adx_severe_thresh or chop >= chop_squeeze_thresh)
        )

        if is_severe_chop:
            reasons.append(f"Severe Chop on {tf_label} (CHOP: {chop:.1f} >= {chop_severe_thresh}, ADX: {adx:.1f} < {adx_severe_thresh})")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.CHOP_CONSOLIDATION
                primary_label = f"🛑 NO TRADE ZONE (CONSOLIDATION / CHOP - {tf_label})"
                badge = f"CHOP-{tf_label} ({chop:.0f})"
        elif is_coiled_squeeze:
            reasons.append(f"Coiled Squeeze without expansion on {tf_label} (BBW: {bbw:.2f}%, ADX: {adx:.1f})")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.CHOP_CONSOLIDATION
                primary_label = f"🛑 NO TRADE ZONE (RANGE SQUEEZE - {tf_label})"
                badge = f"SQUEEZE-{tf_label} ({bbw:.1f}%)"
        elif is_middle_chop:
            reasons.append(f"Middle Chop Zone on {tf_label} (Range Pos: {range_pos:.1f}%, ADX: {adx:.1f}). Section 35 capital preservation lock active.")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.CHOP_CONSOLIDATION
                primary_label = f"🛑 NO TRADE ZONE (MIDDLE CHOP - {tf_label})"
                badge = f"MID-CHOP-{tf_label} ({range_pos:.0f}%)"

        # ----------------------------------------------------------------------
        # PILLAR 2: LOW VOLUME & ILLIQUIDITY (Dry book, slippage traps)
        # ----------------------------------------------------------------------
        vol_24h_quote = 0.0
        if stats_24h:
            try:
                if isinstance(stats_24h, (int, float)):
                    vol_24h_quote = float(stats_24h)
                elif isinstance(stats_24h, dict):
                    vol_24h_quote = float(stats_24h.get('quoteVolume') or stats_24h.get('volume_24h_usd') or stats_24h.get('volume_24h') or 0.0)
            except Exception:
                vol_24h_quote = 0.0

        # Strict Tier-2 Liquidity Floor: $1.0M USDT baseline
        # Even for exempt strategies, trading below $1M incurs severe slippage and wide spread
        effective_min_vol = max(1_000_000.0, (min_quote_vol * 0.50) if is_exempt_strategy else min_quote_vol)
        is_sub_liquidity = (vol_24h_quote > 0 and vol_24h_quote < effective_min_vol)

        # Multi-day rolling volume check: If rolling volume across recent daily history is dry (< $1M)
        if (not is_sub_liquidity) and df is not None and "volume" in df.columns and len(df) >= 3:
            try:
                tf_clean_str = str(anchor_tf or "").lower()
                if any(k in tf_clean_str for k in ["1d", "daily", "24h", "1w", "15d"]):
                    rolling_daily_usd = float((df["volume"].iloc[-3:] * df["close"].iloc[-3:]).mean())
                    if 0 < rolling_daily_usd < 1_000_000.0:
                        is_sub_liquidity = True
                        vol_24h_quote = rolling_daily_usd
            except Exception:
                pass
        # Dynamically adapt RVOL floor: relax during quiet sessions if verified OB trigger, coiling compression, or boundary setup exists
        effective_rvol_thresh = rvol_dry_thresh
        if is_exempt_strategy:
            effective_rvol_thresh = max(0.35, rvol_dry_thresh - 0.25)
        elif ob_setup and ob_setup.get("setup_detected"):
            effective_rvol_thresh = max(0.40, rvol_dry_thresh - 0.20)
        elif adx >= 20.0:
            effective_rvol_thresh = max(0.45, rvol_dry_thresh - 0.15)

        # Low relative volume during chop/squeeze or attempted breakout
        is_dry_breakout = (rvol < effective_rvol_thresh and any(k in decision.upper() for k in ["BREAKOUT", "PUMP", "MOMENTUM", "CHASE"]))
        is_dry_volume_lull = (not is_exempt_strategy) and (rvol < effective_rvol_thresh and (chop >= chop_squeeze_thresh or adx < adx_severe_thresh))

        if is_sub_liquidity:
            reasons.append(f"Sub-Threshold Illiquidity (${vol_24h_quote/1e6:.2f}M < ${effective_min_vol/1e6:.1f}M USDT). Trading halted to eliminate slippage traps on thin books.")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.DRY_VOLUME_ILLIQUID
                primary_label = f"🛑 NO TRADE ZONE (SUB-THRESHOLD ILLIQUIDITY - {tf_label})"
                badge = f"ILLIQUID (${vol_24h_quote/1e6:.1f}M)"
        elif is_dry_breakout:
            reasons.append(f"Dry Volume Breakout Deficit on {tf_label} (RVOL: {rvol:.2f}x < {effective_rvol_thresh}x)")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.DRY_VOLUME_ILLIQUID
                primary_label = f"🛑 NO TRADE ZONE (BREAKOUT LACKS VOLUME - {tf_label})"
                badge = f"LOW VOL-{tf_label} ({rvol:.2f}x)"
        elif is_dry_volume_lull:
            reasons.append(f"Dry Volume Consolidation on {tf_label} (RVOL: {rvol:.2f}x < {effective_rvol_thresh}x)")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.DRY_VOLUME_ILLIQUID
                primary_label = f"🛑 NO TRADE ZONE (LOW VOLUME / CHOP - {tf_label})"
                badge = f"LOW VOL-{tf_label} ({rvol:.2f}x)"

        # ----------------------------------------------------------------------
        # PILLAR 3: MID-RANGE "NO MAN'S LAND" (Middle 40%-60% in range market)
        # ----------------------------------------------------------------------
        # In a range market (not trending), trading dead in the middle gives 50/50 odds
        is_range_regime = (adx < 24.0 or chop >= 52.0)
        is_mid_range = (42.0 <= range_pos <= 58.0)

        # Exception: don't block if there is a verified institutional Order Block retest at the current price
        has_fresh_ob = bool(ob_setup and ob_setup.get("setup_detected"))

        if is_range_regime and is_mid_range and not is_exempt_strategy:
            reasons.append(f"Dead Mid-Range Position ({range_pos:.1f}% inside Bollinger Band)")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.MID_RANGE_CHOP
                primary_label = "🛑 NO TRADE ZONE (Mid-Range 50/50 No Man's Land)"
                badge = f"MID-RANGE ({range_pos:.0f}%)"

        # ----------------------------------------------------------------------
        # PILLAR 4: LACK OF INSTITUTIONAL CONFIRMATION (Fakeouts & Mid-air setups)
        # ----------------------------------------------------------------------
        # 1. Wick Fakeouts: Attempted long breakout with huge upper wick (>50%) that closed red
        if direction.upper() in ["LONG", "BULLISH"] and upper_wick_ratio >= 0.50 and is_red_candle and not has_cleared_rejection:
            reasons.append(f"Unconfirmed Long Breakout (Upper Wick {upper_wick_ratio*100:.0f}% rejected)")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.UNCONFIRMED_WICK_FAKEOUT
                primary_label = "🛑 NO TRADE ZONE (Upper Wick Rejection Fakeout)"
                badge = "WICK FAKEOUT (Upper Rejection)"

        # 2. Wick Fakeouts: Attempted short breakdown with huge lower wick (>50%) that closed green
        if direction.upper() in ["SHORT", "BEARISH"] and lower_wick_ratio >= 0.50 and is_green_candle and not has_cleared_absorption:
            reasons.append(f"Unconfirmed Short Breakdown (Lower Wick {lower_wick_ratio*100:.0f}% absorbed)")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.UNCONFIRMED_WICK_FAKEOUT
                primary_label = "🛑 NO TRADE ZONE (Lower Wick Absorption Fakeout)"
                badge = "WICK FAKEOUT (Lower Absorption)"

        # 3. Order Block Mid-Air Setup (Claimed OB but price is far away from mitigation zone)
        if ob_setup and ob_setup.get("setup_detected"):
            mitigated = ob_setup.get("mitigated", False)
            in_zone = bool(ob_setup.get("in_order_block_zone") or ob_setup.get("is_touching") or ob_setup.get("state") == "TESTING")
            if not in_zone and not mitigated:
                reasons.append("Unconfirmed Order Block (Price hovering in mid-air outside block)")
                if primary_code == NoTradeZoneReason.CLEAR:
                    primary_code = NoTradeZoneReason.UNCONFIRMED_OB_MID_AIR
                    primary_label = "🛑 NO TRADE ZONE (Awaiting Order Block Retest)"
                    badge = "AWAITING OB RETEST"

        # 4. Multi-Timeframe Dead-Zone Alignment (-20% to +20%) + Indecisive ML Probability (46%-52%)
        if abs(alignment_score) <= 15.0 and (0.47 <= meta_win_prob <= 0.52):
            reasons.append(f"Conflict Multi-Timeframe Alignment ({alignment_score:+.1f}%) and Flat ML Edge ({meta_win_prob*100:.1f}%)")
            if primary_code == NoTradeZoneReason.CLEAR:
                primary_code = NoTradeZoneReason.DEAD_ZONE_ALIGNMENT
                primary_label = "🛑 NO TRADE ZONE (Multi-Timeframe Conflict & Flat Alpha)"
                badge = "CONFLICT ALIGNMENT"

        # ----------------------------------------------------------------------
        # PILLAR 5: MACRO REGIME & EVENT BLACKOUT
        # ----------------------------------------------------------------------
        # 1. Macro BTC Shield No Trade Zone (Volatility Squeeze / Blackout / Crash)
        if btc_shield_info:
            is_btc_ntz = (
                btc_shield_info.get("is_ntz_active", False) or
                btc_shield_info.get("status_code") == "NO_TRADE_ZONE" or
                "NO_TRADE_ZONE" in str(btc_shield_info.get("altcoin_posture", "")) or
                btc_shield_info.get("regime") == "RANGE_SQUEEZE"
            )
            is_btc_dump = (
                btc_shield_info.get("is_active") or
                btc_shield_info.get("status_code") in ["ALERT_DUMP", "FLASH_DUMP", "DUMP", "BEAR_CASCADE_BLACKOUT"] or
                btc_shield_info.get("regime") == "FLASH_DUMP" or
                "DEFENSIVE_CASH_ONLY" in str(btc_shield_info.get("altcoin_posture", ""))
            )

            if is_btc_ntz:
                reason_str = btc_shield_info.get("reason", "BTC Volatility Squeeze / Coiling Consolidation")
                if not is_exempt_strategy:
                    reasons.append(f"Macro BTC No Trade Zone Active: {reason_str}")
                    if primary_code == NoTradeZoneReason.CLEAR:
                        primary_code = NoTradeZoneReason.CHOP_CONSOLIDATION
                        primary_label = f"🛑 NO TRADE ZONE (BTC Macro Volatility Squeeze: {reason_str})"
                        badge = "MACRO NTZ"
            elif is_btc_dump and direction.upper() in ["LONG", "BULLISH"]:
                reason_str = btc_shield_info.get("reason", "BTC Flash Dump Active")
                reasons.append(f"BTC Shield Active: {reason_str}")
                if primary_code == NoTradeZoneReason.CLEAR:
                    primary_code = NoTradeZoneReason.MACRO_BTC_CASCADE
                    primary_label = f"🛑 NO TRADE ZONE (BTC Market Cascade: {reason_str})"
                    badge = "BTC DUMP CASCADE"

        # 2. Pre-Event News Blackout Window (<45 mins to high-impact catalyst)
        if fund_matrix:
            cat_ev = fund_matrix.get("catalyst_event", {})
            if cat_ev and cat_ev.get("is_sell_the_news_danger_zone"):
                reasons.append("High-Impact Event Blackout Window Active (<12h to Major Catalyst)")
                if primary_code == NoTradeZoneReason.CLEAR:
                    primary_code = NoTradeZoneReason.PRE_EVENT_BLACKOUT
                    primary_label = "🛑 NO TRADE ZONE (Pre-Event Catalyst Blackout)"
                    badge = "EVENT BLACKOUT"

        # 3. Extreme Funding Rate Crowding
        if funding_info:
            fr_rate = float(funding_info.get("funding_rate", 0.0) or 0.0)
            if fr_rate >= 0.0008 and direction.upper() in ["LONG", "BULLISH"]:
                reasons.append(f"Extreme Long Crowding (Funding Rate: {fr_rate*100:+.3f}% / 8h)")
                if primary_code == NoTradeZoneReason.CLEAR:
                    primary_code = NoTradeZoneReason.EXTREME_FUNDING_CROWD
                    primary_label = "🛑 NO TRADE ZONE (Extreme Funding Long Squeeze Hazard)"
                    badge = f"HIGH FR ({fr_rate*100:+.2f}%)"
            elif fr_rate <= -0.0006 and direction.upper() in ["SHORT", "BEARISH"]:
                reasons.append(f"Extreme Short Crowding (Funding Rate: {fr_rate*100:+.3f}% / 8h)")
                if primary_code == NoTradeZoneReason.CLEAR:
                    primary_code = NoTradeZoneReason.EXTREME_FUNDING_CROWD
                    primary_label = "🛑 NO TRADE ZONE (Extreme Funding Short Squeeze Hazard)"
                    badge = f"NEGATIVE FR ({fr_rate*100:+.2f}%)"

        # Final Assembly
        is_ntz = (primary_code != NoTradeZoneReason.CLEAR)
        if not is_ntz:
            primary_code = NoTradeZoneReason.CLEAR
            primary_label = "🟢 TRADE ZONE APPROVED"
            badge = "APPROVED"

        return {
            "is_ntz": is_ntz,
            "code": primary_code.value,
            "label": primary_label,
            "badge": badge,
            "timeframe": tf_label,
            "reasons": reasons,
            "allowed_to_trade": not is_ntz,
            "metrics": {
                "chop_index": round(chop, 1),
                "adx": round(adx, 1),
                "rvol": round(rvol, 2),
                "range_pos_pct": round(range_pos, 1),
                "bbw_pct": round(bbw, 2),
                "upper_wick_ratio": round(upper_wick_ratio, 2),
                "lower_wick_ratio": round(lower_wick_ratio, 2)
            }
        }


# Global singleton instance
no_trade_zone_engine = NoTradeZoneEngine()
