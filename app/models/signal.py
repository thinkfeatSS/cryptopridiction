from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index
from datetime import datetime, timezone
import math
from app.database import Base

def _safe_float(v, fallback=None):
    if v is None:
        return fallback
    try:
        val = float(v)
        return fallback if (math.isnan(val) or math.isinf(val)) else val
    except Exception:
        return fallback

class SignalAudit(Base):
    __tablename__ = "signals_tracker"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    signal_id = Column(String(128), unique=True, index=True, nullable=False)
    date_utc = Column(String(32), index=True)
    time_utc = Column(String(32))
    rank_label = Column(String(32))
    quality_grade = Column(String(255), index=True)
    grade_tier = Column(Integer, default=2, index=True)  # 1: A+, 2: A, 3: B+, 4: C
    symbol = Column(String(32), index=True, nullable=False)
    horizon = Column(String(32), index=True)  # SCALP (15M), DAY (1H), SWING (24H)
    direction = Column(String(16), index=True)  # LONG / SHORT
    conviction_pct = Column(Float, default=50.0)
    entry_price = Column(Float, nullable=False)
    tp1_price = Column(Float)
    tp2_price = Column(Float)
    tp3_price = Column(Float)
    sl_price = Column(Float)
    sl_original = Column(Float, nullable=True)
    risk_reward_ratio = Column(String(16), default="1:2.0")
    expected_return_pct = Column(Float, default=0.0)
    decision = Column(String(255))
    paper_trading_status = Column(String(255))
    predicted_window = Column(String(255))
    predicted_close_utc = Column(String(64))
    status = Column(String(32), default="PENDING_EVALUATION", index=True)
    outcome_label = Column(String(255), default="PENDING ⏳", index=True)
    peak_price_seen = Column(Float)
    trough_price_seen = Column(Float)
    max_potential_gain_pct = Column(Float, default=0.0)
    exit_price = Column(Float, nullable=True)
    realized_return_pct = Column(Float, nullable=True)  # Clean float for aggregations
    evaluated_at_utc = Column(String(64), nullable=True)
    meta_win_prob = Column(Float, nullable=True)
    meta_win_prob_pct = Column(Float, nullable=True)
    volume_24h_usd = Column(Float, nullable=True)
    spread_bps = Column(Float, nullable=True)
    tf_metrics_json = Column(Text, nullable=True)
    card_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_sig_sym_date', 'symbol', 'date_utc'),
        Index('idx_sig_status_outcome', 'status', 'outcome_label'),
        Index('idx_sig_grade_horizon', 'grade_tier', 'horizon'),
        Index('idx_sig_date_status', 'date_utc', 'status'),
    )

    def _resolve_canonical_outcome(self) -> str:
        """Resolves authoritative outcome category (PENDING, WON, LOST, BREAKEVEN, EXPIRED)."""
        try:
            from app.quant_v16.audit import classify_signal_outcome
            return classify_signal_outcome(self.status, self.outcome_label, self.realized_return_pct)
        except Exception:
            st = str(self.status or "").strip().upper()
            out = str(self.outcome_label or "").strip().upper()
            if any(k in st for k in ["PENDING", "ACTIVE", "RESTING"]) or "PENDING" in out or "AWAIT" in out or "RESTING" in out:
                return "PENDING"
            if any(k in st for k in ["BREAKEVEN", "TIER0", "_BE"]) or "BREAKEVEN" in out or "TIER-0" in out:
                return "BREAKEVEN"
            if "WON" in st or "WON" in out:
                return "WON"
            if "LOST" in st or "LOST" in out or "STOPPED" in out:
                return "LOST"
            if "EXP" in st or "EXPIRED" in out:
                return "EXPIRED"
            return "PENDING"

    def to_dict(self):
        # 1. Authoritative Calibrated Machine Learning Probability
        if getattr(self, "meta_win_prob_pct", None) is not None and self.meta_win_prob_pct > 0:
            win_p = round(float(self.meta_win_prob_pct), 1)
        elif getattr(self, "meta_win_prob", None) is not None and self.meta_win_prob > 0:
            win_p = round(float(self.meta_win_prob) * 100.0, 1)
        else:
            # Neutral empirical baseline (36.7%) when model output is unpopulated
            win_p = 36.7

        # 2. Path Probabilities with Mathematical Coherence: P(SL) = 100 - P(TP1), P(TP3) <= P(TP2) <= P(TP1)
        p_tp1 = round(max(5.0, min(95.0, win_p)), 1)
        p_sl = round(max(5.0, 100.0 - p_tp1), 1)
        p_tp2 = round(p_tp1 * 0.65, 1)
        p_tp3 = round(p_tp2 * 0.55, 1)

        canonical_outcome = self._resolve_canonical_outcome()
        ret_val = _safe_float(self.realized_return_pct, None)
        exit_p = _safe_float(self.exit_price, None)
        entry_p = _safe_float(self.entry_price, 0.0)

        # Robust Dynamic Accounting (Quant Edge Rule 1, 6 & 9):
        # Resolved/terminal trades must never show null return or evaluating state.
        if ret_val is None and canonical_outcome != "PENDING":
            if exit_p is not None and entry_p and entry_p > 0:
                if str(self.direction or "").upper() == "SHORT":
                    ret_val = round(((entry_p - exit_p) / entry_p) * 100.0, 2)
                else:
                    ret_val = round(((exit_p - entry_p) / entry_p) * 100.0, 2)
            else:
                ret_val = 0.0
                if exit_p is None:
                    exit_p = entry_p

        curr_p = _safe_float(getattr(self, "current_price", None), None) or (exit_p if any(k in str(self.status or "") for k in ["WON", "LOST", "EXP", "CANCEL", "CLOSE"]) else entry_p)
        live_pnl = _safe_float(getattr(self, "live_pnl_pct", None), None)

        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "date_utc": self.date_utc,
            "time_utc": self.time_utc,
            "rank": self.rank_label,
            "quality_grade": self.quality_grade,
            "grade_tier": self.grade_tier,
            "symbol": self.symbol,
            "horizon": self.horizon,
            "direction": self.direction,
            "conviction_pct": _safe_float(self.conviction_pct, 50.0),
            "win_p": win_p,
            "win_prob": win_p,
            "meta_win_prob": round(win_p / 100.0, 4),
            "meta_win_prob_pct": win_p,
            "meta_win_probability": round(win_p / 100.0, 4),
            "meta_win_probability_pct": win_p,
            "path_probabilities": {
                "tp1": p_tp1,
                "tp2": p_tp2,
                "tp3": p_tp3,
                "sl": p_sl
            },
            "p_tp1_pct": p_tp1,
            "p_tp2_pct": p_tp2,
            "p_tp3_pct": p_tp3,
            "p_sl_pct": p_sl,
            "entry_price": entry_p,
            "tp1_price": _safe_float(self.tp1_price, None),
            "tp2_price": _safe_float(self.tp2_price, None),
            "tp3_price": _safe_float(self.tp3_price, None),
            "sl_price": _safe_float(self.sl_price, None),
            "risk_reward_ratio": self.risk_reward_ratio,
            "expected_return_pct": _safe_float(self.expected_return_pct, 0.0),
            "decision": self.decision,
            "paper_trading_status": self.paper_trading_status,
            "predicted_window": self.predicted_window,
            "predicted_close_utc": self.predicted_close_utc,
            "status": self.status,
            "outcome": canonical_outcome,
            "outcome_label": self.outcome_label,
            "peak_price_seen": _safe_float(self.peak_price_seen, None),
            "trough_price_seen": _safe_float(self.trough_price_seen, None),
            "max_potential_gain_pct": _safe_float(self.max_potential_gain_pct, 0.0),
            "exit_price": exit_p,
            "realized_return_pct": f"{ret_val:+.2f}%" if ret_val is not None else "",
            "realized_return_num": ret_val,
            "evaluated_at_utc": self.evaluated_at_utc or "",
            "volume_24h_usd": _safe_float(getattr(self, "volume_24h_usd", None), None),
            "spread_bps": _safe_float(getattr(self, "spread_bps", None), None),
            "tf_metrics_json": self.tf_metrics_json,
            "card": self.card_text,
            "trade_id": self.signal_id,
            "current_price": curr_p,
            "pnl_pct": live_pnl if self.status == "ACTIVE" else (ret_val if ret_val is not None else 0.0),
            "live_pnl_pct": live_pnl,
        }
