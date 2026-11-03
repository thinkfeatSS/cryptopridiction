import time
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class BtcPredictiveMarketShield:
    """
    🛡️ PREDICTIVE BITCOIN MARKET BETA SHIELD & MACRO REGIME FORECASTER
    Evaluates:
    - Multi-timeframe trend structure (15M, 1H, 4H, 1D EMAs)
    - Institutional Rolling Volume-Weighted Average Price (1H & 4H VWAP)
    - Choppiness Index (Trend vs Chop) & ADX momentum
    - Bollinger Band Width Squeeze (Volatility compression detection)
    - Predictive price target projections & Altcoin Risk Posture gating
    """

    def __init__(self):
        self.state: Dict[str, Any] = {
            "active": False,
            "status_code": "NORMAL",
            "regime": "MARKET_STABLE",
            "regime_label": "🟢 MARKET STABLE / OPPORTUNITY NORMAL",
            "reason": "Bitcoin trading cleanly above key structural moving averages.",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "btc_price": 0.0,
            "predicted_trend": "CONSOLIDATION",
            "trend_probability": 65.0,
            "bull_trend_prob": 35.0,
            "bear_trend_prob": 20.0,
            "consolidation_prob": 45.0,
            "predicted_btc_target": 0.0,
            "predicted_btc_change_pct": 0.0,
            "breakout_prediction": "⚖️ RANGE BOUND",
            "altcoin_posture": "STANDARD_EXECUTION",
            "is_ntz_active": False,
            "is_squeeze": False,
            "vol_ratio": 1.0,
            "composite_score": 75.0,
            "last_updated_ts": 0.0
        }

    def evaluate_regime(self, btc_dfs: Dict[str, pd.DataFrame], live_btc_price: float = None) -> Dict[str, Any]:
        """Evaluates live market conditions using Bitcoin's multi-timeframe candle datasets."""
        now_ts = time.time()
        df_15m = btc_dfs.get("15m")
        df_1h = btc_dfs.get("1h")
        df_4h = btc_dfs.get("4h")
        df_1d = btc_dfs.get("1d")

        if df_15m is None or len(df_15m) < 10:
            return self.state

        c_now = float(live_btc_price) if (live_btc_price is not None and live_btc_price > 0) else float(df_15m["close"].iloc[-1])
        c_prev_15m = float(df_15m["close"].iloc[-2])
        ret_15m = (c_now - c_prev_15m) / (c_prev_15m + 1e-10)

        # 1H technicals
        ret_1h = 0.0
        ema20_1h = c_now
        ema50_1h = c_now
        vwap_1h = c_now
        if df_1h is not None and len(df_1h) >= 15:
            ret_1h = (c_now - float(df_1h["close"].iloc[-2])) / (float(df_1h["close"].iloc[-2]) + 1e-10)
            ema20_1h = float(df_1h["close"].ewm(span=20, adjust=False).mean().iloc[-1])
            ema50_1h = float(df_1h["close"].ewm(span=50, adjust=False).mean().iloc[-1])
            # 1H VWAP
            sub_1h = df_1h.iloc[-min(24, len(df_1h)):]
            vol_sum = float(sub_1h["volume"].sum())
            if vol_sum > 0:
                typ = (sub_1h["high"] + sub_1h["low"] + sub_1h["close"]) / 3.0
                vwap_1h = float((typ * sub_1h["volume"]).sum() / vol_sum)

        # 4H technicals
        ret_4h = 0.0
        ema50_4h = c_now
        if df_4h is not None and len(df_4h) >= 10:
            ret_4h = (c_now - float(df_4h["close"].iloc[-2])) / (float(df_4h["close"].iloc[-2]) + 1e-10)
            ema50_4h = float(df_4h["close"].ewm(span=50, adjust=False).mean().iloc[-1])

        # 1D Macro trend
        ret_24h = 0.0
        ema50_1d = c_now
        if df_1d is not None and len(df_1d) >= 10:
            ret_24h = (c_now - float(df_1d["close"].iloc[-2])) / (float(df_1d["close"].iloc[-2]) + 1e-10)
            ema50_1d = float(df_1d["close"].ewm(span=50, adjust=False).mean().iloc[-1])

        # Multi-day 48H micro-volatility calculation
        btc_atr_48h_pct = 1.0
        try:
            if df_1h is not None and len(df_1h) >= 24:
                window_h = min(48, len(df_1h))
                sub_h = df_1h.iloc[-window_h:]
                tr_48 = np.maximum(
                    sub_h["high"] - sub_h["low"],
                    np.maximum((sub_h["high"] - sub_h["close"].shift(1)).abs(),
                               (sub_h["low"] - sub_h["close"].shift(1)).abs())
                )
                atr_48 = float(tr_48.mean())
                btc_atr_48h_pct = float((atr_48 / (c_now + 1e-10)) * 100.0)
            elif df_4h is not None and len(df_4h) >= 6:
                window_4h = min(12, len(df_4h))
                sub_4h = df_4h.iloc[-window_4h:]
                tr_48 = np.maximum(
                    sub_4h["high"] - sub_4h["low"],
                    np.maximum((sub_4h["high"] - sub_4h["close"].shift(1)).abs(),
                               (sub_4h["low"] - sub_4h["close"].shift(1)).abs())
                )
                atr_48 = float(tr_48.mean())
                btc_atr_48h_pct = float((atr_48 / (c_now + 1e-10)) * 100.0)
            elif df_1d is not None and len(df_1d) >= 2:
                sub_1d = df_1d.iloc[-2:]
                tr_48 = np.maximum(
                    sub_1d["high"] - sub_1d["low"],
                    np.maximum((sub_1d["high"] - sub_1d["close"].shift(1)).abs(),
                               (sub_1d["low"] - sub_1d["close"].shift(1)).abs())
                )
                atr_48 = float(tr_48.mean())
                btc_atr_48h_pct = float((atr_48 / (c_now + 1e-10)) * 100.0)
        except Exception:
            btc_atr_48h_pct = 1.0

        # 15M Squeeze & Volatility
        c_series = df_15m["close"]
        h_series = df_15m["high"]
        l_series = df_15m["low"]
        sma20_15m = c_series.rolling(20).mean().iloc[-1]
        std20_15m = c_series.rolling(20).std().iloc[-1]
        bb_upper = sma20_15m + 2.0 * std20_15m
        bb_lower = sma20_15m - 2.0 * std20_15m
        bbw_15m = (bb_upper - bb_lower) / (sma20_15m + 1e-10)

        # True range & ATR
        tr = np.maximum(h_series - l_series, np.maximum((h_series - c_series.shift(1)).abs(), (l_series - c_series.shift(1)).abs()))
        atr_15m = float(tr.rolling(14).mean().iloc[-1])
        base_atr = float(tr.rolling(32).mean().iloc[-1]) if len(tr) >= 32 else atr_15m
        vol_ratio = (atr_15m / (base_atr + 1e-10)) if base_atr > 0 else 1.0

        # Choppiness index on BTC 15M
        try:
            tr1 = h_series - l_series
            tr2 = (h_series - c_series.shift(1)).abs()
            tr3 = (l_series - c_series.shift(1)).abs()
            tr_btc = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr_sum_btc = tr_btc.rolling(14).sum().iloc[-1]
            denom_btc = (h_series.rolling(14).max().iloc[-1] - l_series.rolling(14).min().iloc[-1])
            if denom_btc > 1e-8 and atr_sum_btc > 0:
                raw_chop = float(100.0 * (np.log10(atr_sum_btc / denom_btc) / np.log10(14)))
                btc_chop_15m = max(0.0, min(100.0, raw_chop))
            else:
                btc_chop_15m = 50.0
        except Exception:
            btc_chop_15m = 50.0

        # ---------------------------------------------------------------------
        # UNIFIED QUANT EDGE V16 MACRO REGIME CLASSIFICATION (Section 28-29)
        # ---------------------------------------------------------------------
        from app.quant_v16.regime import compute_live_btc_regime

        regime_v16 = "RANGE"
        bull_prob = 18.0
        bear_prob = 17.0
        cons_prob = 55.0
        confidence = 0.80
        sizing_mult = 0.70
        adx_val = 20.0
        rsi_val = 50.0
        metrics = {}

        eval_res = {}
        if df_1h is not None and len(df_1h) >= 20:
            try:
                prev_r = self.state.get("v16_regime") or self.state.get("regime")
                eval_res = compute_live_btc_regime(df_1h, live_btc_price=c_now, prev_regime=prev_r)
                regime_v16 = eval_res["regime"]
                probs = eval_res.get("probabilities", {})
                bull_prob = round(probs.get("bull", 0.18) * 100.0, 1)
                bear_prob = round(probs.get("bear", 0.17) * 100.0, 1)
                cons_prob = round(probs.get("range", 0.55) * 100.0, 1)
                confidence = eval_res.get("confidence", 0.85)
                sizing_mult = eval_res.get("sizing_multiplier", 1.0)
                metrics = eval_res.get("metrics", {})
                adx_val = metrics.get("adx", 20.0)
                rsi_val = metrics.get("rsi", 50.0)
            except Exception:
                pass

        # Squeeze / NTZ is active when V16 classifies as SQUEEZE (BBW <= 15%ile AND ADX < 20)
        is_squeeze = (regime_v16 == "SQUEEZE")
        bbw_pctile = float(metrics.get("bb_width_percentile", 15.0))
        # Severe flatline stagnation: Extreme dead market (ADX < 12 or BBW <= 3%ile)
        is_dead_flatline = is_squeeze and ((adx_val < 12.0) or (bbw_pctile <= 3.0))
        # Prolonged Multi-Day Micro-Volatility: Ultra-tight band (< 0.50% ATR over 48 hours)
        is_prolonged_micro_vol = (btc_atr_48h_pct > 0.0 and btc_atr_48h_pct < 0.50)
        # Flash dump cascade: Extreme liquidation event
        is_dump_cascade = (ret_15m <= -0.025) or (ret_1h <= -0.05) or (c_now < ema50_1h * 0.95)

        is_ntz_active = False

        if is_dump_cascade:
            status_code = "BEAR_CASCADE_BLACKOUT"
            regime = "FLASH_DUMP"
            regime_label = "🚨 CRITICAL BTC FLASH DUMP (BLACKOUT ACTIVE)"
            reason = f"BTC dumping sharply ({ret_15m*100:+.2f}% on 15m / {ret_1h*100:+.2f}% on 1h). Altcoin longs strictly vetoed."
            alt_longs = False
            alt_posture = "DEFENSIVE_CASH_ONLY"
            shield_active = True
            is_ntz_active = True
            predicted_trend = "BEAR_CASCADE"
            pred_target = round(c_now * 0.97, 2)
            breakout_pred = "🔻 CRITICAL FLUSH"
        elif is_prolonged_micro_vol:
            status_code = "NO_TRADE_ZONE"
            regime = "RANGE_SQUEEZE"
            regime_label = "🛑 PROLONGED MULTI-DAY MICRO-VOLATILITY (NO TRADE ZONE ACTIVE)"
            reason = f"NO TRADE ZONE ACTIVE: Prolonged Multi-Day Micro-Volatility (BTC 48h ATR: {btc_atr_48h_pct:.2f}% < 0.50%). Capital preservation mode active for middle chop; structural boundary touches and coiling breakouts authorized."
            alt_longs = True
            alt_shorts = True
            alt_posture = "NO_TRADE_ZONE_CAPITAL_PRESERVATION"
            shield_active = False
            is_ntz_active = True
            predicted_trend = "SQUEEZE_COILING"
            pred_target = round(c_now, 2)
            breakout_pred = "💤 MICRO-VOL SQUEEZE"
        elif is_dead_flatline:
            status_code = "NO_TRADE_ZONE"
            regime = "RANGE_SQUEEZE"
            regime_label = "🛑 SEVERE FLATLINE STAGNATION (NO TRADE ZONE ACTIVE)"
            reason = f"NO TRADE ZONE ACTIVE: Severe flatline stagnation (ADX: {adx_val:.1f} < 12, BBW %ile: {bbw_pctile:.0f}%). Capital preservation mode active for middle chop; structural boundary touches and coiling breakouts authorized."
            alt_longs = True
            alt_shorts = True
            alt_posture = "NO_TRADE_ZONE_CAPITAL_PRESERVATION"
            shield_active = False
            is_ntz_active = True
            predicted_trend = "SQUEEZE_COILING"
            pred_target = round(c_now, 2)
            breakout_pred = "💤 VOLATILITY SQUEEZE"
        elif is_squeeze:
            status_code = "SQUEEZE_COILING"
            regime = "RANGE_SQUEEZE"
            regime_label = "💤 VOLATILITY COMPRESSION (SELECTIVE ALPHA ACTIVE)"
            reason = f"BTC volatility squeeze coiling (ADX: {adx_val:.1f}, BBW %ile: {bbw_pctile:.0f}%). Section 29 0.60x sizing throttle active."
            alt_longs = True
            alt_posture = "SQUEEZE_SELECTIVE_ALPHA"
            shield_active = False
            is_ntz_active = False
            predicted_trend = "SQUEEZE_COILING"
            pred_target = round(c_now, 2)
            breakout_pred = "💤 VOLATILITY SQUEEZE"
        elif regime_v16 == "BEAR_TREND":
            status_code = "BEAR_TREND"
            regime = "BEAR_TREND"
            regime_label = "🔴 BEAR TREND (SHORT ALPHA AUTHORIZED)"
            reason = f"BTC confirmed macro bear trend below 1H EMA20/50 (ADX: {adx_val:.1f}, RSI: {rsi_val:.1f}). Short strategies authorized with Section 29 1.00x risk multiplier."
            alt_longs = False
            alt_shorts = True
            alt_posture = "BEAR_TREND_SHORT_ALPHA"
            shield_active = False
            is_ntz_active = False
            predicted_trend = "BEAR_TREND"
            pred_target = round(c_now * 0.985, 2)
            breakout_pred = "🔻 BEARISH MOMENTUM"
        elif regime_v16 == "BULL_TREND":
            status_code = "BULL_TREND"
            regime = "BULL_TREND"
            regime_label = "🟢 BULL TREND (BULLISH ALPHA ACTIVE)"
            reason = f"BTC confirmed macro bull trend above 1H EMA20/50 (ADX: {adx_val:.1f}, RSI: {rsi_val:.1f}). Long continuation setups active."
            alt_longs = True
            alt_shorts = False
            alt_posture = "AGGRESSIVE_MOMENTUM_LONGS"
            shield_active = False
            is_ntz_active = False
            predicted_trend = "BULL_TREND"
            pred_target = round(c_now * 1.015, 2)
            breakout_pred = "🚀 BULLISH BREAKOUT"
        elif regime_v16 == "BREAKOUT":
            is_bull = metrics.get("ema_fast", c_now) > metrics.get("ema_slow", c_now)
            status_code = "BREAKOUT"
            regime = "BREAKOUT"
            regime_label = "🚀 MOMENTUM BREAKOUT ACTIVE" if is_bull else "🔻 BREAKDOWN EXPANSION ACTIVE"
            reason = f"BTC high-momentum breakout detected (ADX: {adx_val:.1f})."
            alt_longs = is_bull
            alt_shorts = not is_bull
            alt_posture = "AGGRESSIVE_BREAKOUT" if is_bull else "BREAKDOWN_SHORT_BIAS"
            shield_active = False
            is_ntz_active = False
            predicted_trend = "BREAKOUT_EXPANSION"
            pred_target = round(c_now * (1.02 if is_bull else 0.98), 2)
            breakout_pred = "🚀 BREAKOUT EXPANSION" if is_bull else "🔻 BREAKDOWN EXPANSION"
        elif regime_v16 == "HIGH_VOLATILITY":
            status_code = "HIGH_VOLATILITY"
            regime = "TURBULENT"
            regime_label = "⚠️ HIGH VOLATILITY TURBULENCE"
            reason = f"BTC high volatility expansion (ADX: {adx_val:.1f}). Section 29 0.50x risk throttle active."
            alt_longs = True
            alt_posture = "REDUCED_LEVERAGE"
            shield_active = True
            is_ntz_active = False
            predicted_trend = "VOLATILITY_EXPANSION"
            pred_target = round(c_now * 1.008, 2)
            breakout_pred = "⚡ TURBULENT VOLATILITY"
        else:
            status_code = "RANGE"
            regime = "RANGE"
            regime_label = "⚖️ RANGE BOUND / MEAN REVERSION"
            reason = f"BTC range-bound within statistical corridor (ADX: {adx_val:.1f}, RSI: {rsi_val:.1f}). Section 29 0.70x sizing throttle active."
            alt_longs = True
            alt_posture = "RANGE_BOUND_MEAN_REVERSION"
            shield_active = False
            is_ntz_active = False
            predicted_trend = "CONSOLIDATION"
            pred_target = round(c_now * 1.002, 2)
            breakout_pred = "⚖️ RANGE BOUND"

        # Macro Expansion Readiness Tracking
        bbw_pctile = float(metrics.get('bb_width_percentile', 15.0) or 15.0)
        adx_gap = round(max(0.0, 20.0 - adx_val), 1)
        adx_progress = round(min(100.0, (adx_val / 20.0) * 100.0), 1)
        is_expansion_imminent = (adx_val >= 18.0) or (bbw_pctile > 15.0 and adx_val >= 15.0)

        expansion_readiness = {
            "adx_current": round(adx_val, 1),
            "adx_threshold": 20.0,
            "adx_gap_to_expansion": adx_gap,
            "adx_progress_pct": adx_progress,
            "bbw_percentile": round(bbw_pctile, 1),
            "bbw_threshold": 15.0,
            "is_compression_active": is_squeeze,
            "is_expansion_imminent": is_expansion_imminent,
            "expansion_condition": "ADX >= 20.0 and BBW %ile > 15% with directional candle confirmation",
            "post_expansion_posture": "Emit qualified Grade A+ signals with multi-horizon and fundamental matrix alignment"
        }

        self.state = {
            "active": shield_active,
            "status_code": status_code,
            "regime": regime,
            "regime_label": regime_label,
            "reason": reason,
            "altcoin_longs_allowed": alt_longs,
            "altcoin_shorts_allowed": locals().get("alt_shorts", True),
            "is_ntz_active": is_ntz_active,
            "btc_price": c_now,
            "btc_15m_change_pct": round(ret_15m * 100.0, 2),
            "btc_1h_change_pct": round(ret_1h * 100.0, 2),
            "btc_4h_change_pct": round(ret_4h * 100.0, 2),
            "btc_24h_change_pct": round(ret_24h * 100.0, 2),
            "predicted_trend": predicted_trend,
            "trend_probability": max(bull_prob, bear_prob, cons_prob),
            "bull_trend_prob": bull_prob,
            "bear_trend_prob": bear_prob,
            "consolidation_prob": cons_prob,
            "predicted_btc_target": pred_target,
            "predicted_btc_change_pct": round(((pred_target - c_now) / (c_now + 1e-10)) * 100.0, 2),
            "breakout_prediction": breakout_pred,
            "altcoin_posture": alt_posture,
            "is_squeeze": is_squeeze,
            "bbw_15m_pct": round(bbw_15m * 100.0, 3),
            "vol_ratio": round(vol_ratio, 2),
            "composite_score": round(confidence * 100.0, 1),
            "confidence": confidence,
            "sizing_multiplier": sizing_mult,
            "v16_regime": regime_v16,
            "adx": round(adx_val, 1),
            "bbw_percentile": round(bbw_pctile, 1),
            "is_prolonged_micro_volatility": is_prolonged_micro_vol,
            "btc_atr_48h_pct": round(btc_atr_48h_pct, 2),
            "expansion_readiness": expansion_readiness,
            "last_updated_ts": now_ts
        }
        if eval_res:
            from app.quant_v16.regime import reconcile_btc_shield
            self.state = reconcile_btc_shield(self.state, eval_res)
        return self.state
