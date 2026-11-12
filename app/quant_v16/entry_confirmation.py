"""
QUANT EDGE V16: Institutional Entry Confirmation & Execution Engine
Specifications:
- Real-time Price Action & Microstructure Entry Confirmation
- Strategy 1: Candlestick Trigger Confirmation (Rejection Wick Absorption & Favorable Close)
- Strategy 2: Optimal Entry Zone & Anti-Chase Policy (Resting Limit vs Market Confirmation)
- Strategy 3: Dynamic Price Precision (Zero Hardcoding for High-Value & Sub-Cent Assets)
- Strict Mathematical Alignment with Quant Edge AI V16 Accuracy-First Rules
"""

import math
from typing import Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd


def format_dynamic_precision(price: float) -> float:
    """
    Dynamically rounds price to appropriate institutional decimal precision.
    Prevents sub-cent tokens (PEPE, SHIB, FLOKI, BONK) from collapsing to 0.0,
    and prevents over-precision on high-value coins (BTC, ETH).
    Zero hardcoded symbol lists — dynamic based on value magnitude.
    """
    if price is None or math.isnan(price) or math.isinf(price) or price <= 0:
        return 0.0

    if price >= 1000.0:
        return round(price, 2)
    elif price >= 100.0:
        return round(price, 2)
    elif price >= 1.0:
        return round(price, 4)
    elif price >= 0.01:
        return round(price, 6)
    elif price >= 0.0001:
        return round(price, 8)
    else:
        # Micro sub-cent tokens
        return round(price, 10)


class EntryConfirmationEngine:
    """
    Authoritative institutional entry confirmation engine.
    Ensures trade execution is backed by physical price-action evidence:
    supply absorption for longs, demand rejection for shorts, and anti-chase limit resting.
    """

    @staticmethod
    def validate_candle_trigger(
        df: pd.DataFrame,
        direction: str,
        current_price: float,
        spread_bps: float = 5.0
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates whether the active/trigger candle confirms trade entry.
        Prevents catching falling knives on longs (red marubozu waterfalls)
        and prevents shorting into strong bullish momentum candles without rejection.
        Incorporates robust volume absorption and bid-ask spread hurdle (<= 35 bps / 0.35%).

        Returns: (is_confirmed: bool, reason: str, metrics: Dict[str, Any])
        """
        if df is None or len(df) == 0:
            # Zero history: permit execution with neutral trigger confirmation
            return True, "Default Trigger Confirmed (Zero candle history)", {}

        # In multi-candle datasets (len(df) >= 2), the authoritative candlestick pattern confirmation
        # must be evaluated on the last completed/closed candle (df.iloc[-2]).
        # The live candle (df.iloc[-1]) is developing in real time and is checked to intercept
        # acute adverse blowouts (>1.2% adverse dump/ramp with no wick absorption).
        # For single-candle fixtures (len(df) == 1), evaluate df.iloc[-1] directly.
        dir_upper = str(direction).upper()
        is_long = dir_upper in ["LONG", "BULLISH", "BUY"]

        if len(df) >= 2:
            live_bar = df.iloc[-1]
            l_open = float(live_bar.get("open", current_price))
            l_close = float(current_price if (current_price is not None and current_price > 0) else live_bar.get("close", current_price))
            l_high = max(float(live_bar.get("high", l_close)), l_close)
            l_low = min(float(live_bar.get("low", l_close)), l_close)
            l_rng = max(1e-10, l_high - l_low)
            l_ret = (l_close - l_open) / max(1e-10, l_open)
            l_lower_wick = max(0.0, min(l_open, l_close) - l_low) / l_rng
            l_upper_wick = max(0.0, l_high - max(l_open, l_close)) / l_rng
            l_close_pos = (l_close - l_low) / l_rng

            # Live Bar Acute Volatile News Spike Shock
            if len(df) >= 15:
                try:
                    hist_ranges = (df["high"].iloc[-15:-1].astype(float) - df["low"].iloc[-15:-1].astype(float)).values
                    live_atr = float(np.mean(hist_ranges)) if len(hist_ranges) > 0 else l_rng
                    if live_atr > 0:
                        l_expansion = l_rng / live_atr
                        l_dual_wick = (l_upper_wick >= 0.35 and l_lower_wick >= 0.35 and l_expansion >= 1.8)
                        l_hyper_exp = (l_expansion >= 3.2)
                        if l_hyper_exp or l_dual_wick:
                            reason_msg = f"Live News Volatility Shock: Developing bar expanded {l_expansion:.1f}x ATR-14. Trading paused during news whipsaw."
                            live_metrics = {
                                "candle_range": l_rng,
                                "upper_wick_ratio": round(l_upper_wick, 4),
                                "lower_wick_ratio": round(l_lower_wick, 4),
                                "body_ratio": round(abs(l_close - l_open) / l_rng, 4),
                                "close_pos_in_range": round(l_close_pos, 4),
                                "is_live_blowout": True,
                                "is_news_volatility_shock": True,
                                "expansion_ratio": round(l_expansion, 2)
                            }
                            return False, reason_msg, live_metrics
                except Exception:
                    pass

            if is_long and l_ret <= -0.012 and l_lower_wick < 0.15 and l_close_pos <= 0.20:
                live_metrics = {
                    "candle_range": l_rng,
                    "upper_wick_ratio": round(l_upper_wick, 4),
                    "lower_wick_ratio": round(l_lower_wick, 4),
                    "body_ratio": round(abs(l_close - l_open) / l_rng, 4),
                    "close_pos_in_range": round(l_close_pos, 4),
                    "is_green": False,
                    "is_red": True,
                    "is_live_blowout": True
                }
                return False, f"Live Candle Waterfall Dump: Acute adverse move ({l_ret*100:.1f}%) in active bar without buyer absorption", live_metrics

            if not is_long and l_ret >= 0.012 and l_upper_wick < 0.15 and l_close_pos >= 0.80:
                live_metrics = {
                    "candle_range": l_rng,
                    "upper_wick_ratio": round(l_upper_wick, 4),
                    "lower_wick_ratio": round(l_lower_wick, 4),
                    "body_ratio": round(abs(l_close - l_open) / l_rng, 4),
                    "close_pos_in_range": round(l_close_pos, 4),
                    "is_green": True,
                    "is_red": False,
                    "is_live_blowout": True
                }
                return False, f"Live Candle Ramp Blowout: Acute adverse rally (+{l_ret*100:.1f}%) in active bar without seller rejection", live_metrics

            trigger_candle = df.iloc[-2]
        else:
            trigger_candle = df.iloc[-1]

        c_open = float(trigger_candle.get("open", current_price))
        c_high = float(trigger_candle.get("high", current_price))
        c_low = float(trigger_candle.get("low", current_price))
        c_close = float(trigger_candle.get("close", current_price))

        rng = max(1e-10, c_high - c_low)
        body = abs(c_close - c_open)
        upper_wick = max(0.0, c_high - max(c_open, c_close))
        lower_wick = max(0.0, min(c_open, c_close) - c_low)

        upper_wick_ratio = upper_wick / rng
        lower_wick_ratio = lower_wick / rng
        body_ratio = body / rng
        is_green = c_close >= c_open
        is_red = c_close < c_open

        # Relative close position within the candle range [0.0 = low, 1.0 = high]
        close_pos_in_range = (c_close - c_low) / rng

        # Calculate Volume Surge & Absorption with Robust Granularity & Spread Gating
        volume_surge_ratio = 1.0
        is_volume_absorption = False
        spread_val = float(spread_bps if spread_bps is not None else 5.0)
        is_spread_acceptable = spread_val <= 35.0  # Max allowable spread hurdle: 0.35% (35 bps)
        c_vol = float(trigger_candle.get("volume", 0.0) or 0.0)
        robust_base_vol = 0.0

        if "volume" in df.columns:
            try:
                hist_vols = df["volume"].iloc[:-1] if len(df) >= 2 else df["volume"]
                if len(hist_vols) > 0:
                    vol_window = hist_vols.iloc[-20:]
                    avg_vol = float(vol_window.mean())
                    median_vol = float(vol_window.median())
                    robust_base_vol = max(avg_vol, median_vol)
                    c_vol = float(trigger_candle.get("volume", 0.0) or 0.0)
                    if robust_base_vol > 0:
                        volume_surge_ratio = round(c_vol / robust_base_vol, 2)
                        # Disqualify absorption if spread exceeds hurdle (thin-book erratic spikes)
                        is_volume_absorption = (volume_surge_ratio >= 1.30) and is_spread_acceptable
            except Exception:
                volume_surge_ratio = 1.0

        # Calculate Taker Buy Volume and CVD Surge Metrics with Institutional BVC Synthesis Fallback
        tb_ratio = 0.50
        cvd_surge = 0.0
        if c_vol > 0:
            try:
                has_valid_tb = "taker_buy_vol" in df.columns and not df["taker_buy_vol"].isna().all() and (df["taker_buy_vol"] > 0).any()
                if has_valid_tb:
                    tb_vol = float(trigger_candle.get("taker_buy_vol", c_vol * 0.5) or (c_vol * 0.5))
                    tb_ratio = round(float(np.clip(tb_vol / (c_vol + 1e-10), 0.0, 1.0)), 4)
                    if len(df) >= 5:
                        v_slice = df["volume"].iloc[-5:].values
                        tb_slice = df["taker_buy_vol"].iloc[-5:].values
                        tot_v = float(np.sum(v_slice))
                        tot_tb = float(np.sum(tb_slice))
                        if tot_v > 0:
                            cvd_surge = round(float(np.clip((2.0 * tot_tb - tot_v) / tot_v, -1.0, 1.0)), 4)
                else:
                    # Institutional Bulk Volume Classification (BVC) synthesis
                    z_val = (c_close - c_open) / rng
                    p_buy_val = 0.5 * (1.0 + math.erf(z_val / 1.4142135623730951))
                    w_skew = 0.25 * (lower_wick_ratio - upper_wick_ratio)
                    tb_ratio = round(float(np.clip(p_buy_val + w_skew, 0.05, 0.95)), 4)
                    cvd_surge = round(float(np.clip((2.0 * tb_ratio - 1.0), -1.0, 1.0)), 4)
            except Exception:
                tb_ratio = 0.50
                cvd_surge = 0.0

        # Intraday Flash Liquidity Drain Detection (Acute volume collapse or vacuum on active candle)
        is_flash_liquidity_drain = False
        flash_drain_reason = ""
        c_turnover = c_vol * c_close
        if len(df) >= 10:
            if "volume" in df.columns and robust_base_vol > 0 and volume_surge_ratio < 0.12:
                is_flash_liquidity_drain = True
                flash_drain_reason = f"Acute volume vacuum ({volume_surge_ratio*100:.0f}% of 20-bar avg < 12%)"
            elif "volume" in df.columns and (0 < c_turnover < 5000.0):
                is_flash_liquidity_drain = True
                flash_drain_reason = f"Sub-threshold turnover (${c_turnover:,.0f} < $5,000 on candle)"
            elif spread_val > 25.0:
                is_flash_liquidity_drain = True
                flash_drain_reason = f"Flash spread expansion ({spread_val:.1f} bps > 25.0 bps limit)"

        # Acute News Volatility Shock & Dual-Wick Whipsaw Detection on Closed Trigger Candle
        is_news_volatility_shock = False
        news_shock_reason = ""
        expansion_ratio = 1.0
        active_atr = rng
        if len(df) >= 5 and "high" in df.columns and "low" in df.columns:
            try:
                h_tr = (df["high"].iloc[-15:].astype(float) - df["low"].iloc[-15:].astype(float)).values
                if len(h_tr) > 0:
                    active_atr = float(np.mean(h_tr))
            except Exception:
                active_atr = rng
        if active_atr <= 0:
            active_atr = rng

        if len(df) >= 15:
            try:
                t_bar_idx = -2 if (len(df) >= 2) else -1
                hist_slice = df.iloc[max(0, len(df) + t_bar_idx - 14):max(1, len(df) + t_bar_idx)]
                if len(hist_slice) > 0 and "high" in hist_slice.columns and "low" in hist_slice.columns:
                    h_tr = (hist_slice["high"].astype(float) - hist_slice["low"].astype(float)).values
                    atr14_val = float(np.mean(h_tr)) if len(h_tr) > 0 else rng
                    if atr14_val > 0:
                        expansion_ratio = rng / atr14_val
                        is_dual_wick_churn = (upper_wick_ratio >= 0.35 and lower_wick_ratio >= 0.35 and expansion_ratio >= 1.8)
                        is_hyper_expansion = (expansion_ratio >= 3.2)

                        # Intrabar Acute News Volatility Shock on live forming candle
                        live_shock = False
                        if len(df) >= 2:
                            live_c = df.iloc[-1]
                            l_rng = float(live_c.get("high", 0.0)) - float(live_c.get("low", 0.0))
                            if (l_rng / atr14_val) >= 3.2:
                                live_shock = True
                                news_shock_reason = f"Active live bar hyper volatility expansion ({l_rng/atr14_val:.1f}x ATR-14)"

                        if is_hyper_expansion or is_dual_wick_churn or live_shock:
                            is_news_volatility_shock = True
                            if not live_shock:
                                if is_hyper_expansion:
                                    news_shock_reason = f"Hyper volatility expansion ({expansion_ratio:.1f}x ATR-14 >= 3.2x limit)"
                                else:
                                    news_shock_reason = f"Extreme dual-wick whipsaw churn ({expansion_ratio:.1f}x ATR-14 with upper {upper_wick_ratio*100:.0f}%, lower {lower_wick_ratio*100:.0f}%)"
            except Exception:
                pass

        # Multi-candle Institutional Patterns: Engulfing Momentum Flip
        is_engulfing = False
        if len(df) >= 3:
            prior_candle = df.iloc[-3]
            p_open = float(prior_candle.get("open", current_price))
            p_close = float(prior_candle.get("close", current_price))
            # Bullish Engulfing: Prior candle red, trigger candle green and body engulfs prior body
            if p_close < p_open and is_green and c_close >= p_open and c_open <= p_close and body_ratio >= 0.50:
                is_engulfing = True
            # Bearish Engulfing: Prior candle green, trigger candle red and body engulfs prior body
            elif p_close > p_open and is_red and c_close <= p_open and c_open >= p_close and body_ratio >= 0.50:
                is_engulfing = True

        # Multi-candle Institutional Patterns: Liquidity Sweep & Reclaim (Turtle Soup / Judas Swing)
        # Scan up to 48 historical completed candles to capture major structural swing points and session extremes
        is_sweep_reclaim = False
        swept_price = None
        if len(df) >= 5:
            lookback_n = min(48, max(4, len(df) - 2))
            start_idx = max(0, len(df) - 2 - lookback_n)
            end_idx = max(start_idx + 1, len(df) - 2)
            prior_window = df.iloc[start_idx:end_idx]
            if is_long:
                prior_swing_low = float(prior_window["low"].min())
                reclaim_floor = prior_swing_low - (0.10 * active_atr)
                if c_low < prior_swing_low and (c_close >= prior_swing_low or (c_close >= reclaim_floor and lower_wick_ratio >= 0.30)):
                    is_sweep_reclaim = True
                    swept_price = prior_swing_low
            else:
                prior_swing_high = float(prior_window["high"].max())
                rejection_ceiling = prior_swing_high + (0.10 * active_atr)
                if c_high > prior_swing_high and (c_close <= prior_swing_high or (c_close <= rejection_ceiling and upper_wick_ratio >= 0.30)):
                    is_sweep_reclaim = True
                    swept_price = prior_swing_high

        # Multi-candle Institutional Patterns: Fair Value Gap (FVG) Retest (50% Consequent Encroachment)
        is_fvg_retest = False
        fvg_gap_ce = None
        # Authoritative SMC FVG is formed by 3 candles strictly PRIOR to the trigger candle.
        # If trigger candle is at t_idx (-2 when unclosed live bar is present, else -1),
        # the 3-candle FVG was formed at [t_idx-3, t_idx-2, t_idx-1] (or offset by 1 at [t_idx-4, t_idx-3, t_idx-2]).
        # The trigger candle then tests into this imbalance gap.
        t_idx = -2 if (len(df) >= 2) else -1
        min_bars_needed = abs(t_idx) + 3  # e.g., 2 + 3 = 5 bars
        if len(df) >= min_bars_needed:
            for offset in [0, 1]:
                if len(df) >= (min_bars_needed + offset):
                    c1 = df.iloc[t_idx - 3 - offset]
                    c3 = df.iloc[t_idx - 1 - offset]
                    c1_h = float(c1.get("high", 0.0))
                    c1_l = float(c1.get("low", 0.0))
                    c3_h = float(c3.get("high", 0.0))
                    c3_l = float(c3.get("low", 0.0))
                    if is_long and c1_h < c3_l:
                        gap_span = c3_l - c1_h
                        if gap_span >= (rng * 0.10):  # Lowered from 0.20 — captures more valid institutional FVGs
                            ce = (c1_h + c3_l) / 2.0
                            # Retest: Trigger candle dips into gap (<= c3_l) and closes above CE
                            if c_low <= c3_l and c_close >= ce and c_low >= (c1_h * 0.995):
                                is_fvg_retest = True
                                fvg_gap_ce = round(ce, 6)
                                break
                    elif not is_long and c1_l > c3_h:
                        gap_span = c1_l - c3_h
                        if gap_span >= (rng * 0.10):  # Lowered from 0.20 — captures more valid institutional FVGs
                            ce = (c1_l + c3_h) / 2.0
                            # Retest: Trigger candle rallies into gap (>= c3_h) and closes below CE
                            if c_high >= c3_h and c_close <= ce and c_high <= (c1_l * 1.005):
                                is_fvg_retest = True
                                fvg_gap_ce = round(ce, 6)
                                break

        # Institutional Pattern: Rolling Volume-Weighted Average Price (VWAP) Pullback Rebound
        is_vwap_bounce = False
        rolling_vwap = None
        if "volume" in df.columns and len(df) >= 15:
            try:
                # Use 48-candle window (halved from 96) to support altcoins with shorter history
                v_slice = df.iloc[-48:] if len(df) >= 48 else df
                typ_p = (v_slice["high"].astype(float) + v_slice["low"].astype(float) + v_slice["close"].astype(float)) / 3.0
                vols = v_slice["volume"].astype(float)
                v_sum = vols.sum()
                if v_sum > 0:
                    rolling_vwap = float((typ_p * vols).sum() / v_sum)
                    if is_long:
                        if c_low <= (rolling_vwap * 1.004) and c_close >= rolling_vwap:
                            is_vwap_bounce = True
                    else:
                        if c_high >= (rolling_vwap * 0.996) and c_close <= rolling_vwap:
                            is_vwap_bounce = True
            except Exception:
                is_vwap_bounce = False

        # Institutional Pattern: Keltner-Bollinger Squeeze Expansion Momentum Eruption
        is_squeeze_expansion = False
        if len(df) >= 20:
            try:
                closes_20 = df["close"].iloc[-20:].astype(float)
                ma20 = float(closes_20.mean())
                std20 = float(closes_20.std(ddof=0))
                h20 = df["high"].iloc[-20:].astype(float)
                l20 = df["low"].iloc[-20:].astype(float)
                atr20 = float((h20 - l20).mean())
                kc_upper = ma20 + (1.5 * atr20)
                kc_lower = ma20 - (1.5 * atr20)
                # Anti-Whipsaw Guard:
                # 1. Real body must be decisive (body_ratio >= 0.50).
                # 2. Rejection wick in expansion direction must be minimal (upper_wick <= 0.28 for Long, lower_wick <= 0.28 for Short).
                # 3. Candle must close firmly at extreme (close_pos >= 0.70 for Long, <= 0.30 for Short).
                # 4. Volatility expansion confirmation: std20 >= (0.70 * atr20) confirms Bollinger Bands are expanding outside compression.
                is_vol_expanding = (std20 >= (0.70 * atr20))
                if is_long and c_close > kc_upper and is_green and body_ratio >= 0.50 and upper_wick_ratio <= 0.28 and close_pos_in_range >= 0.70 and is_vol_expanding:
                    is_squeeze_expansion = True
                elif not is_long and c_close < kc_lower and is_red and body_ratio >= 0.50 and lower_wick_ratio <= 0.28 and close_pos_in_range <= 0.30 and is_vol_expanding:
                    is_squeeze_expansion = True
            except Exception:
                is_squeeze_expansion = False

        dir_upper = str(direction).upper()
        metrics = {
            "candle_range": rng,
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "body_ratio": round(body_ratio, 4),
            "close_pos_in_range": round(close_pos_in_range, 4),
            "is_green": is_green,
            "is_red": is_red,
            "volume_surge_ratio": volume_surge_ratio,
            "is_volume_absorption": is_volume_absorption,
            "spread_bps": spread_val,
            "is_spread_acceptable": is_spread_acceptable,
            "is_engulfing": is_engulfing,
            "is_sweep_reclaim": is_sweep_reclaim,
            "is_fvg_retest": is_fvg_retest,
            "is_vwap_bounce": is_vwap_bounce,
            "is_squeeze_expansion": is_squeeze_expansion,
            "is_range_resistance_rejection": bool((not is_long) and (upper_wick_ratio >= 0.30 and close_pos_in_range <= 0.60)),
            "is_range_support_rejection": bool(is_long and (lower_wick_ratio >= 0.30 and close_pos_in_range >= 0.40)),
            "is_flash_liquidity_drain": is_flash_liquidity_drain,
            "flash_drain_reason": flash_drain_reason,
            "is_news_volatility_shock": is_news_volatility_shock,
            "news_shock_reason": news_shock_reason,
            "expansion_ratio": round(expansion_ratio, 2),
            "taker_buy_ratio": tb_ratio,
            "cvd_surge_5": cvd_surge
        }
        if swept_price is not None:
            metrics["swept_price"] = swept_price
        if fvg_gap_ce is not None:
            metrics["fvg_gap_ce"] = fvg_gap_ce
        if rolling_vwap is not None:
            metrics["rolling_vwap"] = round(rolling_vwap, 6)

        # Rejection of All Trades: Acute News Volatility Shock / Violent Dual-Wick Whipsaw
        if is_news_volatility_shock:
            return False, f"Volatile News Spike Shock: {news_shock_reason}. Trading paused to prevent slippage traps.", metrics

        # ----------------------------------------------------------------------
        # 1. LONG ENTRY CONFIRMATION
        # ----------------------------------------------------------------------
        if dir_upper in ["LONG", "BULLISH", "BUY"]:
            # Rejection of Long: Intraday Flash Liquidity Drain
            if is_flash_liquidity_drain:
                return False, f"Intraday Flash Liquidity Drain: {flash_drain_reason}. Trading halted to eliminate slippage traps on thin books.", metrics

            # Rejection of Long: Heavy Red Marubozu (Waterfall knife catch)
            # Low lower wick (<15%) and close at bottom quartile (<= 25% of range)
            if is_red and lower_wick_ratio < 0.15 and close_pos_in_range <= 0.25 and body_ratio >= 0.65:
                return False, f"Bearish Marubozu Waterfall: No buyer absorption (lower wick {lower_wick_ratio*100:.0f}%, close at bottom {close_pos_in_range*100:.0f}%)", metrics

            # Rejection of Long: Bull Trap Liquidity Sweep / Fakeout Rejection at High
            if len(df) >= 5:
                lookback_n = min(48, max(4, len(df) - 2))
                start_idx = max(0, len(df) - 2 - lookback_n)
                end_idx = max(start_idx + 1, len(df) - 2)
                prior_high_window = df.iloc[start_idx:end_idx]
                prior_swing_high = float(prior_high_window["high"].max())
                rejection_ceiling = prior_swing_high + (0.10 * active_atr)
                if c_high > prior_swing_high and (c_close <= prior_swing_high or (c_close <= rejection_ceiling and upper_wick_ratio >= 0.25)):
                    return False, f"Bull Trap Liquidity Sweep Fakeout: Price swept prior high ({prior_swing_high:.4f}) but rejected with {upper_wick_ratio*100:.0f}% upper wick", metrics

            # Rejection of Long: Extreme upper wick rejection fakeout on green candle
            if is_green and upper_wick_ratio >= 0.40 and close_pos_in_range < 0.50:
                return False, f"Long Upper Wick Blow-off Rejection: Exhaustion wick ({upper_wick_ratio*100:.0f}%) rejected higher prices", metrics

            # Institutional Setup 1: Bullish Engulfing Momentum Flip
            if is_engulfing and is_green and upper_wick_ratio < 0.45:
                metrics["pattern"] = "BULLISH_ENGULFING"
                return True, f"Bullish Engulfing Momentum Flip Confirmed (Body ratio {body_ratio*100:.0f}%, vol surge {volume_surge_ratio:.1f}x)", metrics

            # Institutional Setup 2: Liquidity Sweep & Reclaim (Turtle Soup)
            if is_sweep_reclaim:
                metrics["pattern"] = "LIQUIDITY_SWEEP_RECLAIM"
                return True, f"Bullish Liquidity Sweep & Reclaim Confirmed (Swept {swept_price:.4f} with {lower_wick_ratio*100:.0f}% wick absorption)", metrics

            # Institutional Setup 3: Fair Value Gap Retest
            if is_fvg_retest:
                metrics["pattern"] = "FVG_RETEST_LONG"
                return True, f"Bullish Fair Value Gap 50% Consequent Encroachment Retest Confirmed (CE: {fvg_gap_ce})", metrics

            # Institutional Setup 4: Rolling VWAP Rebound
            if is_vwap_bounce:
                metrics["pattern"] = "VWAP_BOUNCE_LONG"
                return True, f"Bullish Institutional VWAP Rebound Confirmed (VWAP: {rolling_vwap:.4f})", metrics

            # Institutional Setup 5: Squeeze Expansion
            if is_squeeze_expansion:
                metrics["pattern"] = "SQUEEZE_EXPANSION_LONG"
                return True, "Bullish Squeeze Expansion Momentum Eruption Confirmed", metrics

            # Confirmation A: Lower wick absorption / Hammer / Pinbar (Supply absorbed by buyers)
            if lower_wick_ratio >= 0.30 and close_pos_in_range >= 0.40:
                metrics["is_range_support_rejection"] = True
                metrics["pattern"] = "RANGE_SUPPORT_REJECTION"
                return True, f"Lower Wick Absorption Confirmed ({lower_wick_ratio*100:.0f}% wick rejection)", metrics

            # Confirmation B: Bullish close with reasonable upper headroom
            if is_green and upper_wick_ratio < 0.50 and close_pos_in_range >= 0.45:
                return True, f"Bullish Candle Close Confirmed (Close pos {close_pos_in_range*100:.0f}%)", metrics

            # If candle range is tiny relative to price (< 0.05%), treat as neutral coiling
            if (rng / current_price) < 0.0005:
                return True, "Low-Volatility Coiling Trigger Confirmed", metrics

            # Fall-through validation: Distinguish developing green consolidation from unabsorbed red bars
            if is_red:
                # A red candle cannot confirm long entry unless it demonstrates buyer absorption or tight doji consolidation
                if lower_wick_ratio >= 0.25 or is_volume_absorption or (body_ratio <= 0.20 and close_pos_in_range >= 0.35):
                    return True, f"Bullish Absorption on Red Candle Confirmed (Lower wick {lower_wick_ratio*100:.0f}%)", metrics
                return False, f"Awaiting Bullish Absorption: Falling red bar with inadequate lower wick ({lower_wick_ratio*100:.0f}%)", metrics

            if is_green and close_pos_in_range >= 0.35:
                return True, f"Developing Green Candle Confirmed (Close pos {close_pos_in_range*100:.0f}%)", metrics

            return False, f"Awaiting Bullish Absorption: Close in lower range ({close_pos_in_range*100:.0f}%) without absorption wick", metrics

        # ----------------------------------------------------------------------
        # 2. SHORT ENTRY CONFIRMATION
        # ----------------------------------------------------------------------
        elif dir_upper in ["SHORT", "BEARISH", "SELL"]:
            # Rejection of Short: Intraday Flash Liquidity Drain
            if is_flash_liquidity_drain:
                return False, f"Intraday Flash Liquidity Drain: {flash_drain_reason}. Trading halted to eliminate slippage traps on thin books.", metrics

            # Rejection of Short: Heavy Green Marubozu (Ramping pump candle)
            # Low upper wick (<15%) and close at top quartile (>= 75% of range)
            if is_green and upper_wick_ratio < 0.15 and close_pos_in_range >= 0.75 and body_ratio >= 0.65:
                return False, f"Bullish Marubozu Ramp: No seller rejection (upper wick {upper_wick_ratio*100:.0f}%, close at top {close_pos_in_range*100:.0f}%)", metrics

            # Rejection of Short: Bear Trap Liquidity Sweep / Fakeout Rebound at Low
            if len(df) >= 5:
                lookback_n = min(48, max(4, len(df) - 2))
                start_idx = max(0, len(df) - 2 - lookback_n)
                end_idx = max(start_idx + 1, len(df) - 2)
                prior_low_window = df.iloc[start_idx:end_idx]
                prior_swing_low = float(prior_low_window["low"].min())
                reclaim_floor = prior_swing_low - (0.10 * active_atr)
                if c_low < prior_swing_low and (c_close >= prior_swing_low or (c_close >= reclaim_floor and lower_wick_ratio >= 0.25)):
                    return False, f"Bear Trap Liquidity Sweep Absorption: Price swept prior low ({prior_swing_low:.4f}) but absorbed with {lower_wick_ratio*100:.0f}% absorption wick", metrics

            # Rejection of Short: Extreme lower wick absorption fakeout on red candle
            if is_red and lower_wick_ratio >= 0.40 and close_pos_in_range > 0.50:
                return False, f"Short Lower Wick Absorption: Strong buyer floor ({lower_wick_ratio*100:.0f}%) absorbed selling", metrics

            # Institutional Setup 1: Bearish Engulfing Momentum Flip
            if is_engulfing and is_red and lower_wick_ratio < 0.45:
                metrics["pattern"] = "BEARISH_ENGULFING"
                return True, f"Bearish Engulfing Momentum Flip Confirmed (Body ratio {body_ratio*100:.0f}%, vol surge {volume_surge_ratio:.1f}x)", metrics

            # Institutional Setup 2: Liquidity Sweep & Rejection (Judas Swing)
            if is_sweep_reclaim:
                metrics["pattern"] = "LIQUIDITY_SWEEP_REJECTION"
                return True, f"Bearish Liquidity Sweep & Rejection Confirmed (Swept {swept_price:.4f} with {upper_wick_ratio*100:.0f}% wick rejection)", metrics

            # Institutional Setup 3: Fair Value Gap Retest
            if is_fvg_retest:
                metrics["pattern"] = "FVG_RETEST_SHORT"
                return True, f"Bearish Fair Value Gap 50% Consequent Encroachment Retest Confirmed (CE: {fvg_gap_ce})", metrics

            # Institutional Setup 4: Rolling VWAP Rejection
            if is_vwap_bounce:
                metrics["pattern"] = "VWAP_BOUNCE_SHORT"
                return True, f"Bearish Institutional VWAP Rejection Confirmed (VWAP: {rolling_vwap:.4f})", metrics

            # Institutional Setup 5: Squeeze Expansion
            if is_squeeze_expansion:
                metrics["pattern"] = "SQUEEZE_EXPANSION_SHORT"
                return True, "Bearish Squeeze Expansion Downside Breakdown Confirmed", metrics

            # Confirmation A: Upper wick rejection / Shooting Star / Inverted Hammer (Demand rejected by sellers)
            if upper_wick_ratio >= 0.30 and close_pos_in_range <= 0.60:
                metrics["is_range_resistance_rejection"] = True
                metrics["pattern"] = "RANGE_RESISTANCE_REJECTION"
                return True, f"Upper Wick Rejection Confirmed ({upper_wick_ratio*100:.0f}% wick rejection)", metrics

            # Confirmation B: Bearish close with reasonable lower headroom
            if is_red and lower_wick_ratio < 0.50 and close_pos_in_range <= 0.55:
                return True, f"Bearish Candle Close Confirmed (Close pos {close_pos_in_range*100:.0f}%)", metrics

            # If candle range is tiny relative to price (< 0.05%), treat as neutral coiling
            if (rng / current_price) < 0.0005:
                return True, "Low-Volatility Coiling Trigger Confirmed", metrics

            # Fall-through validation: Distinguish developing red distribution from unrejected green bars
            if is_green:
                # A green candle cannot confirm short entry unless it demonstrates seller rejection or tight doji consolidation
                if upper_wick_ratio >= 0.25 or is_volume_absorption or (body_ratio <= 0.20 and close_pos_in_range <= 0.65):
                    return True, f"Bearish Rejection on Green Candle Confirmed (Upper wick {upper_wick_ratio*100:.0f}%)", metrics
                return False, f"Awaiting Bearish Rejection: Ramping green bar with inadequate upper wick ({upper_wick_ratio*100:.0f}%)", metrics

            if is_red and close_pos_in_range <= 0.65:
                return True, f"Developing Red Candle Confirmed (Close pos {close_pos_in_range*100:.0f}%)", metrics

            return False, f"Awaiting Bearish Rejection: Close in upper range ({close_pos_in_range*100:.0f}%) without rejection wick", metrics

        return True, "Unrecognized direction (default pass)", metrics

    @staticmethod
    def calculate_optimal_entry_zone(
        current_price: float,
        ob_setup: Optional[Dict[str, Any]],
        direction: str,
        active_atr: float,
        chase_threshold_pct: float = 0.40,
        strategy: Optional[str] = None,
        candle_metrics: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculates optimal limit entry price, resting bracket zone, and anti-chase classification.
        - For momentum breakouts, engulfing momentum flips, and directional expansions:
          Price action just confirmed continuation! Confirms MARKET_CONFIRMED entry at current_price.
        - For value zone pullbacks (Order Blocks, FVG retests, VWAP bounces, Liquidity Reclaims):
          Anchors limit to the value level. If within chase threshold (<= 0.40%), confirms MARKET_CONFIRMED.
          If price has extended beyond the POI, recommends RESTING_LIMIT to eliminate slippage.
        """
        dir_upper = str(direction).upper()
        is_long = dir_upper in ["LONG", "BULLISH", "BUY"]
        strat_str = str(strategy or "").upper()

        is_momentum_breakout = (
            any(k in strat_str for k in ["MOMENTUM", "BREAKOUT", "EXPANSION", "DIRECTIONAL"]) or
            bool(candle_metrics and candle_metrics.get("is_engulfing")) or
            bool(candle_metrics and candle_metrics.get("is_squeeze_expansion"))
        ) and not (ob_setup and ob_setup.get("setup_detected")) and not (candle_metrics and candle_metrics.get("is_fvg_retest"))

        # 1. Determine optimal entry limit anchor
        if ob_setup and ob_setup.get("optimal_entry_limit"):
            optimal_limit = float(ob_setup["optimal_entry_limit"])
        elif ob_setup and ob_setup.get("mean_threshold_price"):
            optimal_limit = float(ob_setup["mean_threshold_price"])
        elif ob_setup and ob_setup.get("order_block_zone"):
            z = ob_setup["order_block_zone"]
            optimal_limit = (float(z[0]) + float(z[1])) / 2.0
        elif candle_metrics and candle_metrics.get("fvg_gap_ce"):
            optimal_limit = float(candle_metrics["fvg_gap_ce"])
        elif candle_metrics and candle_metrics.get("rolling_vwap") and "VWAP" in strat_str:
            optimal_limit = float(candle_metrics["rolling_vwap"])
        elif candle_metrics and candle_metrics.get("swept_price") and (candle_metrics.get("is_sweep_reclaim") or "LIQUIDITY" in strat_str):
            optimal_limit = float(candle_metrics["swept_price"])
        elif candle_metrics and (candle_metrics.get("is_range_resistance_rejection") or candle_metrics.get("is_range_support_rejection")):
            optimal_limit = current_price
        elif is_momentum_breakout:
            c_rng = float(candle_metrics.get("candle_range") or 0.0) if candle_metrics else 0.0
            exp_ratio = float(candle_metrics.get("expansion_ratio") or 1.0) if candle_metrics else 1.0
            u_wick = float(candle_metrics.get("upper_wick_ratio") or 0.0) if candle_metrics else 0.0
            l_wick = float(candle_metrics.get("lower_wick_ratio") or 0.0) if candle_metrics else 0.0
            body_r = float(candle_metrics.get("body_ratio") or 0.0) if candle_metrics else 0.0
            close_pos = float(candle_metrics.get("close_pos_in_range") or 0.5) if candle_metrics else 0.5
            vol_surge = float(candle_metrics.get("volume_surge_ratio") or 1.0) if candle_metrics else 1.0
            tb_r = float(candle_metrics.get("taker_buy_ratio") or 0.5) if candle_metrics else 0.5
            cvd_s = float(candle_metrics.get("cvd_surge_5") or 0.0) if candle_metrics else 0.0
            is_sqz = bool(candle_metrics and candle_metrics.get("is_squeeze_expansion"))

            # 1. Institutional Parabolic Momentum / Marubozu Continuation Signature:
            # - Extreme directional close (>= 82% for Long, <= 18% for Short)
            # - Negligible counter-wick (upper wick <= 12% for Long, lower wick <= 12% for Short - buyers/sellers completely absorbed)
            # - Decisive candle body (body_ratio >= 60%)
            # - Confirmed aggressive order flow (taker_ratio >= 0.56 or cvd_surge >= 0.12 for Long; <= 0.44 or <= -0.12 for Short)
            # - Strong volume expansion (vol_surge >= 1.25 or squeeze expansion)
            is_parabolic_long = is_long and (close_pos >= 0.82) and (u_wick <= 0.12) and (body_r >= 0.60) and ((tb_r >= 0.56) or (cvd_s >= 0.12)) and ((vol_surge >= 1.25) or is_sqz)
            is_parabolic_short = (not is_long) and (close_pos <= 0.18) and (l_wick <= 0.12) and (body_r >= 0.60) and ((tb_r <= 0.44) or (cvd_s <= -0.12)) and ((vol_surge >= 1.25) or is_sqz)
            is_parabolic_impulse = is_parabolic_long or is_parabolic_short

            # 2. Optimal Entry Limit (OEL) Protocol:
            if is_parabolic_impulse:
                # Strong Parabolic Continuation: Price velocity is high and counter-wicks are negligible.
                # In hyper-momentum (counter-wick <= 6%), execute directly at market to prevent leaving unfilled orders.
                # If minor breath (6% < wick <= 12%), place an aggressive shallow micro-retest limit (0.12 * range).
                counter_wick = u_wick if is_long else l_wick
                if counter_wick <= 0.06:
                    optimal_limit = current_price  # Confirms MARKET_CONFIRMED entry immediately
                else:
                    shallow_offset = 0.12 * c_rng
                    optimal_limit = (current_price - shallow_offset) if is_long else (current_price + shallow_offset)
            else:
                # Standard Breakout with Extension or Counter-Wicks:
                # If breakout candle shows volatility extension or upper/lower seller rejection wicks,
                # anchor limit to 0.382 Fibonacci retracement to prevent buying the top of the wick.
                is_extended_expansion = (
                    (c_rng >= 0.35 * active_atr and active_atr > 0) or
                    (exp_ratio >= 1.25 and c_rng > 0) or
                    (is_long and u_wick >= 0.18 and c_rng > 0) or
                    (not is_long and l_wick >= 0.18 and c_rng > 0)
                )
                if is_extended_expansion and c_rng > 0:
                    pullback_offset = 0.382 * c_rng
                    optimal_limit = (current_price - pullback_offset) if is_long else (current_price + pullback_offset)
                else:
                    optimal_limit = current_price
        else:
            # Dynamic volatility-scaled pullback anchor (Zero hardcoding):
            # Scales pullback depth proportional to active ATR volatility, bounded between 0.15% and 0.80% of current price.
            atr_pct = active_atr / max(1e-8, current_price)
            offset_ratio = float(np.clip(0.15 * atr_pct, 0.0015, 0.0080))
            pullback_offset = current_price * offset_ratio
            optimal_limit = (current_price - pullback_offset) if is_long else (current_price + pullback_offset)

        # Sanity bounds on optimal limit
        if optimal_limit <= 0 or math.isnan(optimal_limit):
            optimal_limit = current_price

        # Distance from optimal entry limit
        dist_pct = (abs(current_price - optimal_limit) / current_price) * 100.0

        # Volatility-scaled dynamic chase tolerance (bounded between 0.20% and 1.25%)
        atr_pct = (active_atr / max(1e-8, current_price)) * 100.0 if active_atr > 0 else 0.50
        base_chase = float(chase_threshold_pct) if chase_threshold_pct is not None else 0.40
        dynamic_chase_pct = float(np.clip(max(0.20, min(base_chase, atr_pct * 0.35)), 0.20, 1.25))
        if is_momentum_breakout and 'is_parabolic_impulse' in locals() and is_parabolic_impulse:
            dynamic_chase_pct = max(dynamic_chase_pct, 0.55)

        # Check if price has run away beyond chase threshold
        is_chasing = False
        chase_warning = ""

        # Order Block Value Zone In-Bounds Check: If price is currently residing inside the detected Order Block zone,
        # it is not chasing; it is resting directly at the institutional point of interest.
        is_inside_ob_zone = False
        if ob_setup and ob_setup.get("order_block_zone"):
            z = ob_setup["order_block_zone"]
            ob_min = min(float(z[0]), float(z[1]))
            ob_max = max(float(z[0]), float(z[1]))
            if ob_min <= current_price <= ob_max:
                is_inside_ob_zone = True

        if not is_inside_ob_zone:
            if is_long and current_price > (optimal_limit * (1.0 + dynamic_chase_pct / 100.0)):
                is_chasing = True
                chase_warning = f"Price extended {dist_pct:.2f}% above optimal POI ({format_dynamic_precision(optimal_limit)}). Await pullback."
            elif not is_long and current_price < (optimal_limit * (1.0 - dynamic_chase_pct / 100.0)):
                is_chasing = True
                chase_warning = f"Price extended {dist_pct:.2f}% below optimal POI ({format_dynamic_precision(optimal_limit)}). Await bounce."

        bracket = 0.25 * max(active_atr, current_price * 0.002)
        # Entry zone spans from optimal limit through current price with bracket padding
        zone_min = format_dynamic_precision(min(optimal_limit, current_price) - bracket)
        zone_max = format_dynamic_precision(max(optimal_limit, current_price) + bracket)
        zone_min = max(current_price * 0.001, zone_min)

        is_limit_pending = is_chasing
        entry_mode = "RESTING_LIMIT" if is_limit_pending else "MARKET_CONFIRMED"
        exec_price = format_dynamic_precision(optimal_limit if is_limit_pending else current_price)

        return {
            "entry_mode": entry_mode,
            "is_limit_pending": is_limit_pending,
            "optimal_entry_price": exec_price,
            "optimal_entry_limit": format_dynamic_precision(optimal_limit),
            "entry_zone_min": zone_min,
            "entry_zone_max": zone_max,
            "distance_from_limit_pct": round(dist_pct, 2),
            "chase_threshold_pct": round(dynamic_chase_pct, 2),
            "is_chasing": is_chasing,
            "chase_warning": chase_warning
        }

    @staticmethod
    def calculate_top5_obi(depth_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculates Level-5 Order Book Imbalance (OBI), notional depth, spread, and micro-price.
        OBI = (Bid_Depth - Ask_Depth) / (Bid_Depth + Ask_Depth) in [-1.0, +1.0]
        """
        if not depth_data or not isinstance(depth_data, dict):
            return {
                "obi_5": 0.0,
                "bid_depth_usd": 0.0,
                "ask_depth_usd": 0.0,
                "best_bid": 0.0,
                "best_ask": 0.0,
                "spread_bps": 0.0,
                "micro_price": 0.0,
                "has_depth": False
            }

        # Check if pre-computed OBI is already available
        if "obi_5" in depth_data and "bid_depth_usd" in depth_data:
            return depth_data

        bids_raw = depth_data.get("bids", [])
        asks_raw = depth_data.get("asks", [])

        if not bids_raw and not asks_raw:
            return {
                "obi_5": float(depth_data.get("obi") or depth_data.get("order_book_imbalance") or 0.0),
                "bid_depth_usd": float(depth_data.get("bid_depth_usd") or 0.0),
                "ask_depth_usd": float(depth_data.get("ask_depth_usd") or 0.0),
                "best_bid": float(depth_data.get("best_bid") or 0.0),
                "best_ask": float(depth_data.get("best_ask") or 0.0),
                "spread_bps": float(depth_data.get("spread_bps") or 0.0),
                "micro_price": float(depth_data.get("micro_price") or 0.0),
                "has_depth": bool(depth_data.get("has_depth", False))
            }

        # Safely parse up to top-5 bids and asks
        top5_bids = []
        for b in bids_raw[:5]:
            if isinstance(b, (list, tuple)) and len(b) >= 2:
                try:
                    p, q = float(b[0]), float(b[1])
                    if p > 0 and q > 0:
                        top5_bids.append((p, q))
                except (ValueError, TypeError):
                    pass
            elif isinstance(b, dict):
                try:
                    p = float(b.get("price") or b.get("p") or 0.0)
                    q = float(b.get("qty") or b.get("quantity") or b.get("q") or 0.0)
                    if p > 0 and q > 0:
                        top5_bids.append((p, q))
                except (ValueError, TypeError):
                    pass

        top5_asks = []
        for a in asks_raw[:5]:
            if isinstance(a, (list, tuple)) and len(a) >= 2:
                try:
                    p, q = float(a[0]), float(a[1])
                    if p > 0 and q > 0:
                        top5_asks.append((p, q))
                except (ValueError, TypeError):
                    pass
            elif isinstance(a, dict):
                try:
                    p = float(a.get("price") or a.get("p") or 0.0)
                    q = float(a.get("qty") or a.get("quantity") or a.get("q") or 0.0)
                    if p > 0 and q > 0:
                        top5_asks.append((p, q))
                except (ValueError, TypeError):
                    pass

        bid_depth_usd = sum(p * q for p, q in top5_bids)
        ask_depth_usd = sum(p * q for p, q in top5_asks)
        tot_depth = bid_depth_usd + ask_depth_usd

        best_bid = top5_bids[0][0] if top5_bids else 0.0
        best_ask = top5_asks[0][0] if top5_asks else 0.0

        if best_bid > 0 and best_ask > best_bid:
            spread_bps = round(((best_ask - best_bid) / best_bid) * 10000.0, 2)
        else:
            spread_bps = 0.0

        if tot_depth > 0:
            obi_5 = round(float(np.clip((bid_depth_usd - ask_depth_usd) / tot_depth, -1.0, 1.0)), 4)
            micro_price = round((best_bid * ask_depth_usd + best_ask * bid_depth_usd) / tot_depth, 6) if (best_bid > 0 and best_ask > 0) else best_bid
        else:
            obi_5 = 0.0
            micro_price = best_bid

        return {
            "obi_5": obi_5,
            "bid_depth_usd": round(bid_depth_usd, 2),
            "ask_depth_usd": round(ask_depth_usd, 2),
            "best_bid": round(best_bid, 6),
            "best_ask": round(best_ask, 6),
            "spread_bps": spread_bps,
            "micro_price": micro_price,
            "has_depth": (len(top5_bids) > 0 and len(top5_asks) > 0)
        }

    @staticmethod
    def validate_resting_limit_fill(
        direction: str,
        limit_price: float,
        current_price: float,
        depth_data: Optional[Dict[str, Any]] = None,
        cvd_metrics: Optional[Dict[str, Any]] = None,
        candle_metrics: Optional[Dict[str, Any]] = None,
        obi_threshold: float = 0.25,
        cvd_threshold: float = 0.20,
        touch_tolerance: float = 0.0
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Authoritative Live OBI / CVD Inflow Confirmation for Resting Limit Fills.
        Connects top-5 order book depth to resting limit order execution:
        - Prevents filling long limits into adverse ask wall avalanches and aggressive market dumps.
        - Prevents filling short limits into adverse bid wall ramps and aggressive market squeezes.
        - Confirms fill when incoming microstructure shows buyer absorption on longs / seller resistance on shorts.

        Returns: (is_fill_confirmed: bool, reason: str, telemetry: Dict[str, Any])
        """
        dir_upper = str(direction).upper()
        is_long = dir_upper in ["LONG", "BULLISH", "BUY"]

        # 1. Price touch verification (with dynamic micro-bracket touch tolerance)
        max_allowed_long_p = limit_price + touch_tolerance
        min_allowed_short_p = limit_price - touch_tolerance
        if is_long and current_price > max_allowed_long_p:
            return False, f"Price (${current_price:,.4f}) above Long limit (${limit_price:,.4f})", {}
        elif not is_long and current_price < min_allowed_short_p:
            return False, f"Price (${current_price:,.4f}) below Short limit (${limit_price:,.4f})", {}

        # 2. Extract Top-5 OBI metrics
        depth_info = EntryConfirmationEngine.calculate_top5_obi(depth_data)
        has_depth = depth_info.get("has_depth", False)
        obi_val = float(depth_info.get("obi_5", 0.0))

        # 3. Extract CVD Surge / Inflow metrics
        # In local test environments without live WebSockets or Redis, falls back to conservative taker-buy volume estimates
        cvd_val = 0.0
        if cvd_metrics and isinstance(cvd_metrics, dict):
            cvd_val = float(cvd_metrics.get("cvd_surge") or cvd_metrics.get("cvd_surge_5") or 0.0)
        elif candle_metrics and isinstance(candle_metrics, dict):
            tb_r_cand = float(candle_metrics.get("taker_buy_ratio", 0.50))
            cvd_raw = candle_metrics.get("cvd_surge_5")
            if cvd_raw is not None and not (isinstance(cvd_raw, float) and np.isnan(cvd_raw)):
                cvd_val = float(cvd_raw)
            elif "taker_buy_ratio" in candle_metrics:
                # Conservative taker-buy volume estimate fallback
                cvd_val = round(float(np.clip(2.0 * tb_r_cand - 1.0, -1.0, 1.0)), 4)
            else:
                cvd_val = 0.0

        # Fallback to high-frequency synthetic taker flow if depth is absent or lagged (> 350ms)
        is_synthetic = False
        depth_lag_ms = float(depth_data.get("latency_ms", 0.0)) if depth_data else 0.0
        if (not has_depth or depth_lag_ms > 350.0) and candle_metrics and isinstance(candle_metrics, dict) and candle_metrics:
            tb_r = float(candle_metrics.get("taker_buy_ratio", 0.50))
            cvd_s = cvd_val
            synth_obi = round(float(np.clip(1.5 * (tb_r - 0.50) + 0.5 * cvd_s, -1.0, 1.0)), 4)
            obi_val = synth_obi
            is_synthetic = True

        telemetry = {
            "direction": dir_upper,
            "limit_price": limit_price,
            "current_price": current_price,
            "obi_5": obi_val,
            "cvd_surge": cvd_val,
            "bid_depth_usd": depth_info.get("bid_depth_usd", 0.0),
            "ask_depth_usd": depth_info.get("ask_depth_usd", 0.0),
            "spread_bps": depth_info.get("spread_bps", 0.0),
            "has_depth": has_depth,
            "is_synthetic": is_synthetic
        }

        # 4. Microstructure Inflow Decision Logic
        if is_long:
            # Adverse Long Fill Interception:
            # A. Extreme ask wall depth imbalance (OBI < -0.60 indicates severe bid void / wall collapse)
            is_extreme_ask_void = (has_depth or is_synthetic) and (obi_val < -0.60)
            # B. Heavy ask stacking with aggressive market selling (OBI < -0.25 and CVD < -0.15)
            is_toxic_sell_cascade = (obi_val < -obi_threshold) and (cvd_val < -cvd_threshold)

            if is_extreme_ask_void or is_toxic_sell_cascade:
                reason = f"Adverse ask wall pressure (OBI {obi_val:+.2f} < -{obi_threshold:.2f}, CVD {cvd_val:+.2f}). Awaiting bid absorption inflow."
                telemetry["fill_state"] = "AWAITING_INFLOW"
                return False, reason, telemetry

            # Confirmed Long Fill
            reason = f"Long limit fill confirmed by microstructure absorption (OBI: {obi_val:+.2f}, CVD: {cvd_val:+.2f})"
            telemetry["fill_state"] = "CONFIRMED"
            telemetry["fill_confirmation_type"] = "LIVE_OBI_CVD_CONFIRMED" if (has_depth and not is_synthetic) else ("SYNTHETIC_MICROSTRUCTURE_CONFIRMED" if is_synthetic else "PRICE_TOUCH_FALLBACK")
            return True, reason, telemetry

        else:
            # Adverse Short Fill Interception:
            # A. Extreme bid wall depth imbalance (OBI > +0.60 indicates severe ask void / squeeze breakout)
            is_extreme_bid_void = (has_depth or is_synthetic) and (obi_val > 0.60)
            # B. Heavy bid stacking with aggressive market buying (OBI > +0.25 and CVD > +0.15)
            is_toxic_buy_cascade = (obi_val > obi_threshold) and (cvd_val > cvd_threshold)

            if is_extreme_bid_void or is_toxic_buy_cascade:
                reason = f"Adverse bid wall pressure (OBI {obi_val:+.2f} > +{obi_threshold:.2f}, CVD {cvd_val:+.2f}). Awaiting ask resistance inflow."
                telemetry["fill_state"] = "AWAITING_INFLOW"
                return False, reason, telemetry

            # Confirmed Short Fill
            reason = f"Short limit fill confirmed by microstructure resistance (OBI: {obi_val:+.2f}, CVD: {cvd_val:+.2f})"
            telemetry["fill_state"] = "CONFIRMED"
            telemetry["fill_confirmation_type"] = "LIVE_OBI_CVD_CONFIRMED" if (has_depth and not is_synthetic) else ("SYNTHETIC_MICROSTRUCTURE_CONFIRMED" if is_synthetic else "PRICE_TOUCH_FALLBACK")
            return True, reason, telemetry

    @staticmethod
    def anchor_to_higher_low_and_ob(
        df_15m: pd.DataFrame,
        hl_pivot_price: float,
        current_price: float,
        bullish_ob_low: Optional[float] = None,
        bullish_ob_high: Optional[float] = None,
        opposing_sh_price: Optional[float] = None,
        opposing_supply_low: Optional[float] = None,
        spread_bps: float = 5.0
    ) -> Dict[str, Any]:
        """
        Anchors LONG execution strictly to a confirmed 15M Higher Low (HL) and Bullish Order Block.
        Enforces strict price geometry: SL < Entry < TP1 < TP2 < TP3 with dynamic volatility cushions.
        """
        # Dynamic 15M ATR computation
        atr_15m = 0.0
        if df_15m is not None and len(df_15m) >= 5 and "high" in df_15m.columns and "low" in df_15m.columns:
            h = df_15m["high"].astype(float)
            l = df_15m["low"].astype(float)
            c = df_15m["close"].astype(float)
            tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
            atr_15m = float(tr.rolling(14, min_periods=3).mean().iloc[-1])
        if atr_15m <= 0:
            atr_15m = max(1e-8, current_price * 0.008)

        # Dynamic Entry Zone Anchored to Higher Low (with stale/distant pivot recency guard for 15M scalps)
        hl_price = float(hl_pivot_price if hl_pivot_price and hl_pivot_price > 0 else current_price)
        if df_15m is not None and len(df_15m) >= 8 and current_price > 0 and "low" in df_15m.columns and "close" in df_15m.columns:
            max_hl_dist = min(1.80 * atr_15m, current_price * 0.016)
            if (current_price - hl_price) > max_hl_dist:
                recent_lows = df_15m["low"].iloc[-12:].astype(float).values
                local_hl = None
                for idx in range(len(recent_lows) - 2, 0, -1):
                    if recent_lows[idx] <= recent_lows[idx - 1] and recent_lows[idx] <= recent_lows[idx + 1]:
                        if hl_price < recent_lows[idx] < (current_price - 0.15 * atr_15m):
                            local_hl = float(recent_lows[idx])
                            break
                if local_hl is not None:
                    candidate_hl = local_hl
                elif bullish_ob_high is not None and float(bullish_ob_high) > 0 and float(bullish_ob_high) < current_price:
                    candidate_hl = float(bullish_ob_high)
                else:
                    ema9_val = float(df_15m["close"].iloc[-16:].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                    candidate_hl = min(ema9_val, current_price - 0.35 * atr_15m)
                floor_bound = max(hl_price, current_price - max_hl_dist)
                ceil_bound = current_price - (0.20 * atr_15m)
                if ceil_bound > floor_bound:
                    hl_price = float(np.clip(candidate_hl, floor_bound, ceil_bound))
                else:
                    hl_price = float(floor_bound)

        zone_floor = hl_price - (0.10 * atr_15m)
        zone_ceiling = hl_price + (0.35 * atr_15m)
        if bullish_ob_high is not None and bullish_ob_high > hl_price and bullish_ob_high <= current_price:
            zone_ceiling = max(zone_ceiling, float(bullish_ob_high))

        # Check active candle bounce confirmation on 15M
        candle_has_bounce = True
        if df_15m is not None and len(df_15m) > 0 and "close" in df_15m.columns and "open" in df_15m.columns:
            c_now = float(df_15m["close"].iloc[-1])
            o_now = float(df_15m["open"].iloc[-1])
            h_now = float(df_15m["high"].iloc[-1]) if "high" in df_15m.columns else max(c_now, o_now)
            l_now = float(df_15m["low"].iloc[-1]) if "low" in df_15m.columns else min(c_now, o_now)
            rng_now = max(1e-8, h_now - l_now)
            # If current candle is strongly dumping red without lower wick bounce, do not market-buy falling knife
            is_dumping_red = (c_now < o_now) and ((c_now - l_now) < 0.20 * rng_now)
            if is_dumping_red:
                candle_has_bounce = False

        # Strict Higher Low Anchoring:
        # A Long entry must be strictly executed AT the Higher Low (within the confirmed Higher Low zone).
        # If price has extended above the Higher Low zone (current_price > zone_ceiling), it must NEVER market chase.
        # It must execute as RESTING_LIMIT anchored to the Higher Low.
        is_extended = current_price > zone_ceiling
        if is_extended:
            execution_mode = "RESTING_LIMIT"
            entry_price = format_dynamic_precision(hl_price)
            decision_label = f"🟢 BUY 15M LIMIT (AWAIT PULLBACK TO HL @ ${entry_price})"
        elif current_price < zone_floor or not candle_has_bounce:
            # Price is retesting deep below the HL or candle is still dumping red: Place resting limit at HL
            execution_mode = "RESTING_LIMIT"
            entry_price = format_dynamic_precision(hl_price)
            decision_label = f"🟢 BUY 15M LIMIT (AWAIT PULLBACK TO HL @ ${entry_price})"
        else:
            # Price is strictly AT THE HIGHER LOW (zone_floor <= current_price <= zone_ceiling) with confirmed bounce
            execution_mode = "MARKET_TRIGGER"
            entry_price = format_dynamic_precision(current_price)
            decision_label = f"🟢 BUY 15M (HIGHER LOW RETEST @ ${entry_price})"

        # Stop Loss: Anchored strictly below the structural floor with dynamic volatility & spread noise floor
        ob_is_local = (bullish_ob_low is not None and 0 < float(bullish_ob_low) and (hl_price - float(bullish_ob_low)) <= (1.50 * atr_15m))
        structural_floor = min(hl_price, float(bullish_ob_low)) if ob_is_local else hl_price
        spread_drag_usd = (spread_bps * 0.0001) * entry_price
        vol_cushion = max(0.60 * atr_15m, 4.0 * spread_drag_usd, entry_price * 0.0060)
        min_sl_dist = max(1.00 * atr_15m, 5.0 * spread_drag_usd, entry_price * 0.0120)
        sl_price = format_dynamic_precision(min(structural_floor - vol_cushion, entry_price - min_sl_dist))

        # Invariant assertion: SL must be strictly below Entry by at least the noise floor
        if sl_price >= entry_price or (entry_price - sl_price) < (min_sl_dist * 0.90):
            sl_price = format_dynamic_precision(entry_price - max(1.00 * atr_15m, min_sl_dist))

        risk_amount = max(1e-8, entry_price - sl_price)

        # Take Profit Targets: Anchored to opposing swing high liquidity and Fibonacci extensions
        target_ref = opposing_sh_price
        if opposing_supply_low is not None and opposing_supply_low > entry_price:
            target_ref = min(target_ref, opposing_supply_low) if target_ref else opposing_supply_low

        if target_ref is None or target_ref <= entry_price:
            target_ref = entry_price + (2.0 * risk_amount)

        # Take Profit Targets: Strictly enforce 1:2 Risk to Reward Ratio (Risk = 1.0, Reward = 2.0)
        # TP1: Strictly 2.0 * Risk (1:2 R:R)
        tp1_candidate = entry_price + (2.0 * risk_amount)
        tp1_price = format_dynamic_precision(tp1_candidate)

        # TP2: Runner tranche target (3.0 * Risk or opposing swing high beyond TP1)
        tp2_candidate = entry_price + (3.0 * risk_amount)
        if target_ref is not None and float(target_ref) > tp1_price:
            tp2_candidate = max(tp2_candidate, float(target_ref))
        tp2_price = format_dynamic_precision(tp2_candidate)

        # TP3: Extended runner tranche target (4.0 * Risk or Fibonacci expansion)
        tp3_candidate = entry_price + (4.0 * risk_amount)
        if tp3_candidate <= tp2_price:
            tp3_candidate = tp2_price + (1.0 * risk_amount)
        tp3_price = format_dynamic_precision(tp3_candidate)

        # Final invariant verification
        assert sl_price < entry_price < tp1_price < tp2_price < tp3_price, (
            f"Long price geometry violation: SL={sl_price}, Entry={entry_price}, "
            f"TP1={tp1_price}, TP2={tp2_price}, TP3={tp3_price}"
        )

        rr_ratio = round((tp1_price - entry_price) / risk_amount, 2)

        return {
            "direction": "LONG",
            "execution_mode": execution_mode,
            "decision_label": decision_label,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
            "risk_reward_ratio": rr_ratio,
            "hl_pivot_price": format_dynamic_precision(hl_price),
            "structural_floor": format_dynamic_precision(structural_floor),
            "atr_15m": format_dynamic_precision(atr_15m),
            "entry_zone": [format_dynamic_precision(zone_floor), format_dynamic_precision(zone_ceiling)],
            "is_extended": is_extended,
        }

    @staticmethod
    def anchor_to_lower_high_and_ob(
        df_15m: pd.DataFrame,
        lh_pivot_price: float,
        current_price: float,
        bearish_ob_low: Optional[float] = None,
        bearish_ob_high: Optional[float] = None,
        opposing_sl_price: Optional[float] = None,
        opposing_demand_high: Optional[float] = None,
        spread_bps: float = 5.0
    ) -> Dict[str, Any]:
        """
        Anchors SHORT execution strictly to a confirmed 15M Lower High (LH) and Bearish Order Block.
        Enforces strict price geometry: SL > Entry > TP1 > TP2 > TP3 with dynamic volatility cushions.
        """
        # Dynamic 15M ATR computation
        atr_15m = 0.0
        if df_15m is not None and len(df_15m) >= 5 and "high" in df_15m.columns and "low" in df_15m.columns:
            h = df_15m["high"].astype(float)
            l = df_15m["low"].astype(float)
            c = df_15m["close"].astype(float)
            tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
            atr_15m = float(tr.rolling(14, min_periods=3).mean().iloc[-1])
        if atr_15m <= 0:
            atr_15m = max(1e-8, current_price * 0.008)

        # Dynamic Entry Zone Anchored to Lower High (with stale/distant pivot recency guard for 15M scalps)
        lh_price = float(lh_pivot_price if lh_pivot_price and lh_pivot_price > 0 else current_price)
        if df_15m is not None and len(df_15m) >= 8 and current_price > 0 and "high" in df_15m.columns and "close" in df_15m.columns:
            max_lh_dist = min(1.80 * atr_15m, current_price * 0.016)
            if (lh_price - current_price) > max_lh_dist:
                recent_highs = df_15m["high"].iloc[-12:].astype(float).values
                local_lh = None
                for idx in range(len(recent_highs) - 2, 0, -1):
                    if recent_highs[idx] >= recent_highs[idx - 1] and recent_highs[idx] >= recent_highs[idx + 1]:
                        if (current_price + 0.15 * atr_15m) < recent_highs[idx] < lh_price:
                            local_lh = float(recent_highs[idx])
                            break
                if local_lh is not None:
                    candidate_lh = local_lh
                elif bearish_ob_low is not None and float(bearish_ob_low) > 0 and float(bearish_ob_low) > current_price:
                    candidate_lh = float(bearish_ob_low)
                else:
                    ema9_val = float(df_15m["close"].iloc[-16:].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                    candidate_lh = max(ema9_val, current_price + 0.35 * atr_15m)
                floor_bound = current_price + (0.20 * atr_15m)
                ceil_bound = min(lh_price, current_price + max_lh_dist)
                if ceil_bound > floor_bound:
                    lh_price = float(np.clip(candidate_lh, floor_bound, ceil_bound))
                else:
                    lh_price = float(ceil_bound)

        zone_ceiling = lh_price + (0.10 * atr_15m)
        zone_floor = lh_price - (0.35 * atr_15m)
        if bearish_ob_low is not None and bearish_ob_low < lh_price and bearish_ob_low >= current_price:
            zone_floor = min(zone_floor, float(bearish_ob_low))

        # Check active candle rejection confirmation on 15M
        candle_has_rejection = True
        if df_15m is not None and len(df_15m) > 0 and "close" in df_15m.columns and "open" in df_15m.columns:
            c_now = float(df_15m["close"].iloc[-1])
            o_now = float(df_15m["open"].iloc[-1])
            h_now = float(df_15m["high"].iloc[-1]) if "high" in df_15m.columns else max(c_now, o_now)
            l_now = float(df_15m["low"].iloc[-1]) if "low" in df_15m.columns else min(c_now, o_now)
            rng_now = max(1e-8, h_now - l_now)
            # If current candle is strongly pumping green without upper wick rejection, do not market-sell into rocket
            is_pumping_green = (c_now > o_now) and ((h_now - c_now) < 0.20 * rng_now)
            if is_pumping_green:
                candle_has_rejection = False

        # Strict Lower High Anchoring:
        # A Short entry must be strictly executed AT the Lower High (within the confirmed Lower High zone).
        # If price has dumped below the Lower High zone (current_price < zone_floor), it must NEVER sell the bottom.
        # It must execute as RESTING_LIMIT anchored to the Lower High.
        is_extended = current_price < zone_floor
        if is_extended:
            execution_mode = "RESTING_LIMIT"
            entry_price = format_dynamic_precision(lh_price)
            decision_label = f"🔴 SELL 15M LIMIT (AWAIT BOUNCE TO LH @ ${entry_price})"
        elif current_price > zone_ceiling or not candle_has_rejection:
            # Price is retesting deep above the LH or candle is still driving green: Place resting limit at LH
            execution_mode = "RESTING_LIMIT"
            entry_price = format_dynamic_precision(lh_price)
            decision_label = f"🔴 SELL 15M LIMIT (AWAIT BOUNCE TO LH @ ${entry_price})"
        else:
            # Price is strictly AT THE LOWER HIGH (zone_floor <= current_price <= zone_ceiling) with confirmed rejection
            execution_mode = "MARKET_TRIGGER"
            entry_price = format_dynamic_precision(current_price)
            decision_label = f"🔴 SELL 15M (LOWER HIGH REJECTION @ ${entry_price})"

        # Stop Loss: Anchored strictly above the structural ceiling with dynamic volatility & spread noise floor
        ob_is_local = (bearish_ob_high is not None and float(bearish_ob_high) > 0 and (float(bearish_ob_high) - lh_price) <= (1.50 * atr_15m))
        structural_ceiling = max(lh_price, float(bearish_ob_high)) if ob_is_local else lh_price
        spread_drag_usd = (spread_bps * 0.0001) * entry_price
        vol_cushion = max(0.60 * atr_15m, 4.0 * spread_drag_usd, entry_price * 0.0060)
        min_sl_dist = max(1.00 * atr_15m, 5.0 * spread_drag_usd, entry_price * 0.0120)
        sl_price = format_dynamic_precision(max(structural_ceiling + vol_cushion, entry_price + min_sl_dist))

        # Invariant assertion: SL must be strictly above Entry by at least the noise floor
        if sl_price <= entry_price or (sl_price - entry_price) < (min_sl_dist * 0.90):
            sl_price = format_dynamic_precision(entry_price + max(1.00 * atr_15m, min_sl_dist))

        risk_amount = max(1e-8, sl_price - entry_price)

        # Take Profit Targets: Anchored to opposing swing low liquidity and Fibonacci extensions
        target_ref = opposing_sl_price
        if opposing_demand_high is not None and opposing_demand_high < entry_price:
            target_ref = max(target_ref, opposing_demand_high) if target_ref else opposing_demand_high

        if target_ref is None or target_ref >= entry_price:
            target_ref = entry_price - (2.0 * risk_amount)

        # Take Profit Targets: Strictly enforce 1:2 Risk to Reward Ratio (Risk = 1.0, Reward = 2.0)
        # TP1: Strictly 2.0 * Risk (1:2 R:R)
        tp1_candidate = entry_price - (2.0 * risk_amount)
        tp1_price = format_dynamic_precision(tp1_candidate)

        # TP2: Runner tranche target (3.0 * Risk or opposing swing low beyond TP1)
        tp2_candidate = entry_price - (3.0 * risk_amount)
        if target_ref is not None and float(target_ref) < tp1_price:
            tp2_candidate = min(tp2_candidate, float(target_ref))
        tp2_price = format_dynamic_precision(tp2_candidate)

        # TP3: Extended runner tranche target (4.0 * Risk)
        tp3_candidate = entry_price - (4.0 * risk_amount)
        if tp3_candidate >= tp2_price:
            tp3_candidate = tp2_price - (1.0 * risk_amount)
        tp3_price = format_dynamic_precision(tp3_candidate)

        # Final invariant verification
        assert sl_price > entry_price > tp1_price > tp2_price > tp3_price, (
            f"Short price geometry violation: SL={sl_price}, Entry={entry_price}, "
            f"TP1={tp1_price}, TP2={tp2_price}, TP3={tp3_price}"
        )

        rr_ratio = round((entry_price - tp1_price) / risk_amount, 2)

        return {
            "direction": "SHORT",
            "execution_mode": execution_mode,
            "decision_label": decision_label,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
            "risk_reward_ratio": rr_ratio,
            "lh_pivot_price": format_dynamic_precision(lh_price),
            "structural_ceiling": format_dynamic_precision(structural_ceiling),
            "atr_15m": format_dynamic_precision(atr_15m),
            "entry_zone": [format_dynamic_precision(zone_floor), format_dynamic_precision(zone_ceiling)],
            "is_extended": is_extended,
        }
