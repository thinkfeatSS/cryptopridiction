import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

class CandleDynamicsFeatureExtractor:
    """
    Advanced Feature Extractor specializing in:
    1. Number and streaks of Bullish vs Bearish candles.
    2. Candle Volume dynamics (volume surges, bull vs bear volume ratio, volume-weighted body intensity).
    3. Candle Volatility dynamics (body-to-wick ratio, wick rejections, true range expansion, Garman-Klass vol).
    4. Multi-period momentum indicators.
    """

    @staticmethod
    def extract_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
        if df is None or len(df) < 5:
            return pd.DataFrame()

        data = df.copy()
        c = data["close"]
        h = data["high"]
        l = data["low"]
        o = data["open"]
        v = data["volume"]
        pfx = f"{prefix.rstrip('_')}_" if prefix else ""

        feats = pd.DataFrame(index=data.index)
        bar_range = (h - l).clip(lower=1e-10)
        body = (c - o)
        abs_body = body.abs()

        # =====================================================================
        # 1. BULLISH & BEARISH CANDLE COUNTS AND STREAKS
        # =====================================================================
        is_green = (c > o).astype(float)
        is_red = (c < o).astype(float)

        feats[f"{pfx}is_green"] = is_green
        feats[f"{pfx}is_red"] = is_red

        # Rolling Bull/Bear Ratios
        feats[f"{pfx}bull_ratio_3"] = is_green.rolling(3).mean()
        feats[f"{pfx}bull_ratio_5"] = is_green.rolling(5).mean()
        feats[f"{pfx}bull_ratio_10"] = is_green.rolling(10).mean()
        feats[f"{pfx}bull_ratio_20"] = is_green.rolling(20).mean()

        # Consecutive Streaks
        streak = np.zeros(len(data), dtype=np.float32)
        cur_streak = 0
        for i in range(len(data)):
            if is_green.iloc[i] == 1.0:
                cur_streak = cur_streak + 1 if cur_streak > 0 else 1
            elif is_red.iloc[i] == 1.0:
                cur_streak = cur_streak - 1 if cur_streak < 0 else -1
            else:
                cur_streak = 0
            streak[i] = cur_streak
        feats[f"{pfx}candle_streak"] = streak
        feats[f"{pfx}green_streak_active"] = (streak > 0).astype(float)
        feats[f"{pfx}red_streak_active"] = (streak < 0).astype(float)

        # Higher Highs & Lower Lows
        higher_high = (h > h.shift(1)).astype(float)
        lower_low = (l < l.shift(1)).astype(float)
        feats[f"{pfx}higher_high_streak"] = higher_high.rolling(3).sum()
        feats[f"{pfx}lower_low_streak"] = lower_low.rolling(3).sum()

        # Candle Sequence Net Momentum Delta
        feats[f"{pfx}candle_momentum_delta_10"] = is_green.rolling(10).sum() - is_red.rolling(10).sum()

        # =====================================================================
        # 2. CANDLE VOLUME DYNAMICS
        # =====================================================================
        vol_sma20 = v.rolling(20).mean()
        vol_surge = v / (vol_sma20 + 1e-10)
        feats[f"{pfx}volume_surge_ratio"] = vol_surge.clip(0.1, 10.0)

        # Bull Volume vs Bear Volume Ratios
        bull_vol = np.where(c > o, v, 0.0)
        bear_vol = np.where(c < o, v, 0.0)
        sum_vol5 = v.rolling(5).sum() + 1e-10
        sum_vol14 = v.rolling(14).sum() + 1e-10
        feats[f"{pfx}bull_vol_ratio_5"] = (pd.Series(bull_vol, index=data.index).rolling(5).sum() / sum_vol5).clip(0.0, 1.0)
        feats[f"{pfx}bull_vol_ratio_14"] = (pd.Series(bull_vol, index=data.index).rolling(14).sum() / sum_vol14).clip(0.0, 1.0)

        # Volume-Weighted Body Delta & Intensity
        feats[f"{pfx}vol_weighted_body_delta"] = ((body / (o + 1e-10)) * vol_surge).clip(-0.5, 0.5)
        feats[f"{pfx}volume_intensity"] = (vol_surge * (body / bar_range)).clip(-5.0, 5.0)

        # On-Balance Volume Slope
        obv = np.where(c > c.shift(1), v, np.where(c < c.shift(1), -v, 0.0)).cumsum()
        feats[f"{pfx}obv_slope_5"] = (pd.Series(obv, index=data.index).diff(5) / (v.rolling(5).sum() + 1e-10)).clip(-2.0, 2.0)

        # Taker Buy Volume Ratio & Cumulative Volume Delta (CVD) Order Flow Dynamics
        has_tb = "taker_buy_vol" in data.columns and not data["taker_buy_vol"].isna().all() and (data["taker_buy_vol"] > 0).any()
        if has_tb:
            tb_vol = pd.Series(data["taker_buy_vol"], index=data.index, dtype=float).fillna(v * 0.5)
        else:
            # High-fidelity continuous Bulk Volume Classification (BVC) proxy based on de Prado AFML formulation
            # z = (Close - Open) / Range; P_buy = 0.5 * (1 + erf(z / sqrt(2)))
            # Tail skew = 0.25 * (LowerWick - UpperWick) / Range
            # Inter-bar momentum = 0.10 * (Close - PrevClose) / Range
            z = (c - o) / bar_range
            try:
                import scipy.special
                p_buy = 0.5 * (1.0 + scipy.special.erf(z / 1.4142135623730951))
            except Exception:
                p_buy = 0.5 * (1.0 + np.tanh(z * 0.7978845608))

            upper_w = (h - np.maximum(c, o)) / bar_range
            lower_w = (np.minimum(c, o) - l) / bar_range
            wick_skew = 0.25 * (lower_w - upper_w)
            prev_c = c.shift(1).fillna(c)
            mom = 0.10 * ((c - prev_c) / bar_range).clip(-1.0, 1.0)
            bvc_ratio = pd.Series(p_buy + wick_skew + mom, index=data.index).clip(0.05, 0.95)
            tb_vol = v * bvc_ratio

        tb_vol = tb_vol.clip(lower=0.0)
        feats[f"{pfx}taker_buy_ratio"] = (tb_vol / (v + 1e-10)).clip(0.0, 1.0)
        feats[f"{pfx}taker_buy_ratio_5"] = (tb_vol.rolling(5).sum() / sum_vol5).clip(0.0, 1.0)
        feats[f"{pfx}taker_buy_ratio_14"] = (tb_vol.rolling(14).sum() / sum_vol14).clip(0.0, 1.0)

        # Volume Delta & CVD Surge
        delta_vol = (2.0 * tb_vol) - v
        feats[f"{pfx}cvd_surge_5"] = (delta_vol.rolling(5).sum() / sum_vol5).clip(-1.0, 1.0)
        feats[f"{pfx}cvd_surge_14"] = (delta_vol.rolling(14).sum() / sum_vol14).clip(-1.0, 1.0)

        # =====================================================================
        # 3. CANDLE VOLATILITY DYNAMICS
        # =====================================================================
        # Body-to-Wick Ratio: Measures conviction vs indecision
        feats[f"{pfx}body_to_wick_ratio"] = (abs_body / bar_range).clip(0.0, 1.0)

        # Wick Rejection Tail Dynamics (Buying vs Selling Tails)
        upper_wick = (h - np.maximum(c, o)) / bar_range
        lower_wick = (np.minimum(c, o) - l) / bar_range
        feats[f"{pfx}upper_wick_ratio"] = upper_wick.clip(0.0, 1.0)
        feats[f"{pfx}lower_wick_ratio"] = lower_wick.clip(0.0, 1.0)
        feats[f"{pfx}wick_rejection_balance"] = (lower_wick - upper_wick).clip(-1.0, 1.0)

        # True Range Expansion
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        raw_tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        wilder_tr = raw_tr.ewm(alpha=1/14, adjust=False).mean()
        atr14 = raw_tr.rolling(14).mean()
        feats[f"{pfx}true_range_expansion"] = (raw_tr / (atr14 + 1e-10)).clip(0.1, 8.0)
        feats[f"{pfx}normalized_amplitude"] = (bar_range / (c + 1e-10)).clip(0.0, 0.5)

        # Continuous Volatility Estimators (Garman-Klass)
        log_hl = np.log(h / (l + 1e-10)) ** 2
        log_co = np.log(c / (o + 1e-10)) ** 2
        rs = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
        gk_vol = np.sqrt(rs.rolling(14).mean().clip(lower=0)).fillna(0.0)
        feats[f"{pfx}garman_klass_vol"] = gk_vol

        # =====================================================================
        # 4. TREND, MOMENTUM & MOVING AVERAGES
        # =====================================================================
        ema9 = c.ewm(span=9, adjust=False).mean()
        ema21 = c.ewm(span=21, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()

        feats[f"{pfx}dist_to_ema9"] = (c - ema9) / (c + 1e-10)
        feats[f"{pfx}dist_to_ema21"] = (c - ema21) / (c + 1e-10)
        feats[f"{pfx}dist_to_ema50"] = (c - ema50) / (c + 1e-10)
        feats[f"{pfx}ema9_slope"] = (ema9 - ema9.shift(1)) / (c + 1e-10)

        # RSI (14)
        delta = c.diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs_val = gain / (loss + 1e-10)
        feats[f"{pfx}rsi_14"] = (100.0 - (100.0 / (1.0 + rs_val))) / 100.0

        # ADX (14) - Welles Wilder canonical smoothing (numerator and denominator)
        up_move = h - h.shift(1)
        down_move = l.shift(1) - l
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        plus_di = 100.0 * (pd.Series(plus_dm, index=data.index).ewm(alpha=1/14, adjust=False).mean() / (wilder_tr + 1e-10))
        minus_di = 100.0 * (pd.Series(minus_dm, index=data.index).ewm(alpha=1/14, adjust=False).mean() / (wilder_tr + 1e-10))
        dx = 100.0 * ((plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-10))
        feats[f"{pfx}adx_14"] = (dx.ewm(alpha=1/14, adjust=False).mean()) / 100.0

        # =====================================================================
        # 5. CANDLESTICK PATTERNS & VOLATILITY COMPRESSION SIGNALS
        # =====================================================================
        # Inside Bar (IB) Dynamics: Current bar completely contained within prior bar
        is_inside_bar = ((h <= h.shift(1)) & (l >= l.shift(1))).astype(float)
        feats[f"{pfx}is_inside_bar"] = is_inside_bar
        feats[f"{pfx}inside_bar_cluster_3"] = is_inside_bar.rolling(3).sum()

        # Narrow Range (NR4 / NR7): Range is lowest of past 4 or 7 bars
        is_nr4 = (bar_range == bar_range.rolling(4).min()).astype(float)
        is_nr7 = (bar_range == bar_range.rolling(7).min()).astype(float)
        feats[f"{pfx}is_nr4"] = is_nr4
        feats[f"{pfx}is_nr7"] = is_nr7

        # Indecision Patterns (Doji & Spinning Tops)
        is_doji = ((abs_body / bar_range) < 0.20).astype(float)
        is_spinning_top = (((abs_body / bar_range) < 0.35) & (upper_wick > 0.25) & (lower_wick > 0.25)).astype(float)
        feats[f"{pfx}is_doji"] = is_doji
        feats[f"{pfx}is_spinning_top"] = is_spinning_top

        # Engulfing Expansion Bars
        bull_engulf = ((is_green == 1.0) & (c.shift(1) < o.shift(1)) & (o <= c.shift(1)) & (c >= o.shift(1))).astype(float)
        bear_engulf = ((is_red == 1.0) & (c.shift(1) > o.shift(1)) & (o >= c.shift(1)) & (c <= o.shift(1))).astype(float)
        feats[f"{pfx}bullish_engulfing"] = bull_engulf
        feats[f"{pfx}bearish_engulfing"] = bear_engulf

        # Composite Compression Index: High values indicate spring-loaded coiling
        feats[f"{pfx}compression_intensity"] = (
            (is_inside_bar * 0.35) + 
            (is_nr7 * 0.35) + 
            (is_doji * 0.15) + 
            ((bar_range < atr14 * 0.65).astype(float) * 0.15)
        )

        # Protect live row (-1) from unclosed candle distortion:
        # For discrete pattern features, the state of the completed candle (iloc[-2])
        # represents the established pattern posture at live inference.
        if len(feats) >= 2:
            idx_last = feats.index[-1]
            idx_prev = feats.index[-2]
            for pattern_col in [
                f"{pfx}is_inside_bar",
                f"{pfx}inside_bar_cluster_3",
                f"{pfx}is_nr4",
                f"{pfx}is_nr7",
                f"{pfx}is_doji",
                f"{pfx}is_spinning_top",
                f"{pfx}bullish_engulfing",
                f"{pfx}bearish_engulfing",
                f"{pfx}compression_intensity"
            ]:
                if pattern_col in feats.columns:
                    feats.at[idx_last, pattern_col] = feats.at[idx_prev, pattern_col]

        return feats.replace([np.inf, -np.inf], 0.0).fillna(0.0)
