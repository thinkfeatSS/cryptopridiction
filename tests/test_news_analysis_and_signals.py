import sys
import os
import unittest
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

# Ensure workspace root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.fundamental_service import (
    fundamental_service,
    COIN_NAME_RULES,
    score_headline_nlp,
    parse_event_datetime
)
from app.engine.signals.signal_generator import SignalGenerationSystem
from app.services.whatsapp_service import whatsapp_service
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestNewsAnalysisAndSignals(unittest.TestCase):

    def setUp(self):
        fundamental_service._feed_circuit_breakers.clear()
        fundamental_service._feed_failure_counts.clear()
        fundamental_service._fear_greed_cache = None

    def test_alias_matching_eliminates_near_false_positive(self):
        """Test that common English words like 'near' do not falsely attribute to NEAR Protocol."""
        h1 = "Bitcoin trading near $70,000 as bulls defend support"
        syms1 = fundamental_service.extract_symbols_from_headline(h1)
        self.assertIn("BTC", syms1)
        self.assertNotIn("NEAR", syms1, "Critical: 'near' must not match NEAR Protocol!")

        h2 = "NEAR protocol announces major sharding upgrade for high throughput"
        syms2 = fundamental_service.extract_symbols_from_headline(h2)
        self.assertIn("NEAR", syms2)

        h3 = "Traders accumulate NEAR following dip"
        syms3 = fundamental_service.extract_symbols_from_headline(h3)
        self.assertIn("NEAR", syms3)

    def test_top_40_universe_symbols_recognized(self):
        """Test that top 40 assets like HYPE, WLD, ENA, TRX, ZEC are recognized."""
        h_hype = "Hyperliquid HYPE token launches staking rewards"
        syms_hype = fundamental_service.extract_symbols_from_headline(h_hype)
        self.assertIn("HYPE", syms_hype)

        h_wld = "Worldcoin WLD expands biometric verification to 5 new markets"
        syms_wld = fundamental_service.extract_symbols_from_headline(h_wld)
        self.assertIn("WLD", syms_wld)

        h_ena = "Ethena ENA synthetic dollar supply tops milestone"
        syms_ena = fundamental_service.extract_symbols_from_headline(h_ena)
        self.assertIn("ENA", syms_ena)

        h_trx = "TRON TRX processes record on-chain stablecoin settlement"
        syms_trx = fundamental_service.extract_symbols_from_headline(h_trx)
        self.assertIn("TRX", syms_trx)

    def test_nlp_sentiment_scoring_and_negations(self):
        """Test Bayesian smoothed sentiment scoring, negation handling, and high severity flags."""
        # 1. Bullish
        t_bull = "Institutional digital asset inflows surge to multi-month high"
        score, label, is_sev = score_headline_nlp(t_bull)
        self.assertGreater(score, 0.20)
        self.assertEqual(label, "🟢 BULLISH")
        self.assertFalse(is_sev)

        # 2. Severe Bearish (Exploit / Hack)
        t_exploit = "Initia blockchain halted after exploit reportedly drains over $2.6M"
        score, label, is_sev = score_headline_nlp(t_exploit)
        self.assertLessEqual(score, -0.40)
        self.assertTrue(is_sev, "Exploit must trigger is_high_severity")
        self.assertEqual(label, "🔴 BEARISH")

        # 3. Negation handling: 'object to listings' should not be classified as bullish
        t_neg = "Wells Fargo and six others object to tokenized stock listings"
        score, label, is_sev = score_headline_nlp(t_neg)
        self.assertLessEqual(score, 0.05, "Objection to listings must not be positive bullish")

    def test_event_catalyst_date_parsing(self):
        """Test event catalyst date parsing without string index errors."""
        now = datetime.now(timezone.utc)
        target = now + timedelta(days=6)
        date_str = target.strftime("%Y-%m-%d %H:%M:%S UTC")

        parsed = parse_event_datetime(date_str)
        self.assertIsNotNone(parsed)
        diff_hours = (parsed - now).total_seconds() / 3600.0
        days_until = round(diff_hours / 24.0, 1)
        self.assertAlmostEqual(days_until, 6.0, delta=0.2)

    def test_news_sentinel_vetoes_long_signal_on_negative_news(self):
        """Verify that SignalGenerationSystem vetoes LONG signals on coins with severe negative news."""
        sig_gen = SignalGenerationSystem()

        # Build mock 9 dfs
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq="15min")
        close_prices = np.linspace(100.0, 110.0, 50)
        df_mock = pd.DataFrame({
            "timestamp": [int(d.timestamp() * 1000) for d in dates],
            "open": close_prices - 0.5,
            "high": close_prices + 1.0,
            "low": close_prices - 1.0,
            "close": close_prices,
            "volume": [1000.0] * 50
        })
        dfs_9 = {tf: df_mock.copy() for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]}

        # Synthetic fundamental matrix with severe exploit alert
        bad_fund_matrix = {
            "symbol": "BTC/USDT",
            "base_coin": "BTC",
            "has_severe_negative_news": True,
            "news_sentiment": {
                "score": -0.65,
                "label": "🔴 BEARISH (BLACK SWAN SENTINEL)",
                "has_severe_negative_news": True,
                "top_headline": "Critical bridge exploit drains $100M from network protocol"
            },
            "catalyst_event": {"has_event": False, "is_sell_the_news_danger_zone": False},
            "sizing_multiplier": 0.50,
            "conviction_delta": -15.0
        }

        # Build single horizon signal with bad news
        btc_shield = {"altcoin_longs_allowed": True, "status_code": "NORMAL", "is_ntz_active": False}
        sig = sig_gen._build_single_horizon_signal(
            symbol="BTC/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=110.0,
            dfs_9=dfs_9,
            horizon_prediction={"predicted_change_pct": 2.5, "predicted_target_price": 112.5, "consensus_probability": 0.70},
            btc_shield_state=btc_shield,
            aligned_horizons=["5m", "15m", "1h", "4h", "12h", "1d"],
            fundamental_matrix=bad_fund_matrix
        )

        # Must be VETOED by negative news sentinel
        self.assertFalse(sig["is_trade_active"], "Signal must NOT be active when severe negative news is present!")
        self.assertEqual(sig["signal_status"], "HOLD_VETOED_BY_NEGATIVE_NEWS")
        self.assertIn("NEWS SENTINEL VETO", sig["quality_grade"])
        self.assertEqual(sig["conviction"], 0.0)

    def test_catalyst_momentum_drift_boosts_conviction(self):
        """Verify that pre-event catalyst momentum drift boosts conviction and adds catalyst label."""
        sig_gen = SignalGenerationSystem()

        dates = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq="15min")
        close_prices = np.linspace(2600.0, 2650.0, 50)
        df_mock = pd.DataFrame({
            "timestamp": [int(d.timestamp() * 1000) for d in dates],
            "open": close_prices - 5.0,
            "high": close_prices + 25.0,
            "low": close_prices - 25.0,
            "close": close_prices,
            "volume": [1000.0] * 50
        })
        dfs_9 = {tf: df_mock.copy() for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]}

        good_fund_matrix = {
            "symbol": "ETH/USDT",
            "base_coin": "ETH",
            "has_severe_negative_news": False,
            "news_sentiment": {
                "score": 0.50,
                "label": "🟢 BULLISH",
                "has_severe_negative_news": False,
                "top_headline": "Institutional Ethereum staking ETF approved"
            },
            "catalyst_event": {
                "has_event": True,
                "title": "Mainnet Zero-Knowledge Upgrade",
                "days_until": 5.0,
                "is_sell_the_news_danger_zone": False,
                "is_pre_event_runup": True
            },
            "sizing_multiplier": 1.15,
            "conviction_delta": 8.0
        }

        btc_shield = {"altcoin_longs_allowed": True, "status_code": "NORMAL", "is_ntz_active": False, "v16_regime": "BULL_TREND"}
        from unittest.mock import MagicMock
        sig_gen.meta_labeler.evaluate_signal = MagicMock(return_value={
            "passed_meta_gate": True,
            "win_probability": 0.85,
            "win_probability_pct": 85.0,
            "meta_verdict": "APPROVED",
            "model_type": "PER_COIN_DEDICATED",
            "sample_size": 100
        })

        sig = sig_gen._build_single_horizon_signal(
            symbol="ETH/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=2650.0,
            dfs_9=dfs_9,
            horizon_prediction={"predicted_change_pct": 2.5, "predicted_target_price": 2700.0, "consensus_probability": 0.70},
            btc_shield_state=btc_shield,
            aligned_horizons=["5m", "15m", "1h", "4h", "12h", "1d"],
            fundamental_matrix=good_fund_matrix
        )

        self.assertTrue(sig["is_trade_active"])
        self.assertGreaterEqual(sig["conviction"], 90.0, "Catalyst drift must boost conviction!")
        self.assertIn("EVENT DRIFT", sig["quality_grade"])
        self.assertIsNotNone(sig["fundamental_matrix"])

    def test_whatsapp_formatting_includes_news_and_catalyst(self):
        """Test that format_new_signal in WhatsApp service renders news sentiment and catalyst."""
        sig = {
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "horizon": "1H",
            "quality_grade": "Grade A+ (CATALYST DRIFT)",
            "conviction": 94.0,
            "meta_win_prob_pct": 82.5,
            "entry_price": 180.0,
            "tp1_price": 188.0,
            "tp2_price": 195.0,
            "tp3_price": 205.0,
            "sl_price": 172.0,
            "risk_reward_ratio": "1:2.8",
            "expected_return_pct": 4.5,
            "catalyst_event": {
                "title": "Firedancer Validator Mainnet Launch",
                "days_until": 7.5
            },
            "news_sentiment": {
                "label": "🟢 BULLISH",
                "score": 0.65,
                "top_headline": "Solana ETF applications gain institutional backing"
            }
        }
        msg = whatsapp_service.format_new_signal(sig)
        self.assertIn("SOL_USDT", msg)
        self.assertIn("🚀 *Catalyst:*", msg)
        self.assertIn("Firedancer", msg)
        self.assertIn("📰 *News Flow:*", msg)
        self.assertIn("BULLISH", msg)

    def test_circuit_breaker_trips_on_rate_limit_and_recovers(self):
        """Verify adaptive domain circuit breaker trips on 429/503 and resets on 200/304."""
        test_domain = "test-rate-limit-feed.com"
        # Reset if present
        fundamental_service._record_success(test_domain)
        self.assertFalse(fundamental_service._is_circuit_open(test_domain))

        # Record HTTP 429 (Rate Limit)
        fundamental_service._record_failure(test_domain, status_code=429)
        self.assertTrue(fundamental_service._is_circuit_open(test_domain), "Circuit must be OPEN after 429")

        # Record success
        fundamental_service._record_success(test_domain)
        self.assertFalse(fundamental_service._is_circuit_open(test_domain), "Circuit must be CLOSED after success")

    def test_http_conditional_304_and_caching(self):
        """Verify conditional ETag / Last-Modified caching mechanism."""
        test_url = "https://test-feed.com/rss"
        etag = '"abc-123"'
        last_modified = "Mon, 26 Oct 2026 00:00:00 GMT"
        items = [{"title": "Test Conditional Article", "url": "https://test.com/1"}]

        fundamental_service._save_http_cache(test_url, etag, last_modified, items)
        cond_headers = fundamental_service._get_conditional_headers(test_url)
        self.assertEqual(cond_headers.get("If-None-Match"), etag)
        self.assertEqual(cond_headers.get("If-Modified-Since"), last_modified)

        cached_items = fundamental_service._get_cached_http_items(test_url)
        self.assertEqual(len(cached_items), 1)
        self.assertEqual(cached_items[0]["title"], "Test Conditional Article")

    def test_news_time_decay_fallback_archive(self):
        """
        Verify that when external RSS feeds return 429/503 simultaneously,
        fetch_breaking_news() falls back to cached news records with exponential time-decay.
        """
        now = datetime.now(timezone.utc)
        test_articles = [
            {
                "title": "Historical Bullish Breakout Milestone for Bitcoin",
                "url": "https://test-archive.com/btc",
                "source": "Archive Wire",
                "published_at": (now - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "age_hours": 10.0,
                "currencies": ["BTC"],
                "sentiment_score": 0.80,
                "sentiment_label": "🟢 BULLISH",
                "is_high_severity": False
            },
            {
                "title": "Network Exploit Drains Bridge Liquidity Pool",
                "url": "https://test-archive.com/exploit",
                "source": "Security Sentinel",
                "published_at": (now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "age_hours": 5.0,
                "currencies": ["ETH"],
                "sentiment_score": -0.60,
                "sentiment_label": "🔴 BEARISH (BLACK SWAN SENTINEL)",
                "is_high_severity": True
            }
        ]

        # Save to disk archive
        fundamental_service._save_news_archive(test_articles)

        # Load from disk archive with now + 20 hours (total 30h old)
        future_now = now + timedelta(hours=20)
        restored = fundamental_service._load_news_archive(future_now)
        self.assertGreaterEqual(len(restored), 2)

        btc_art = next(a for a in restored if a.get("title") == "Historical Bullish Breakout Milestone for Bitcoin")
        self.assertAlmostEqual(btc_art["age_hours"], 30.0, delta=0.5)
        # Score must decay: 0.80 * exp(-0.025 * 30) = 0.80 * 0.472 = ~0.38
        self.assertLess(btc_art["sentiment_score"], 0.80)
        self.assertGreater(btc_art["sentiment_score"], 0.20)
        self.assertEqual(btc_art["sentiment_label"], "🟢 BULLISH")

        # Simulate total network blackout: all RSS endpoints returning 429/503
        from unittest.mock import patch, MagicMock
        with patch.object(fundamental_service.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 429
            mock_get.return_value = mock_resp

            # Clear memory cache for test
            fundamental_service._feed_http_cache.clear()

            # Execute fetch_breaking_news under simultaneous rate-limiting
            news = fundamental_service.fetch_breaking_news(force=True)
            self.assertGreater(len(news), 0, "Must fall back to cached records with time-decay!")
            self.assertTrue(any("Bitcoin" in a["title"] for a in news))

    def test_catalyst_resilient_fallback_and_dynamic_synthesis(self):
        """
        Verify that CoinMarketCal rate limits trigger internal fallback
        institutional event schedule without network stalls or static dates.
        """
        now = datetime.now(timezone.utc)
        # Test dynamic protocol milestones synthesis
        milestones = fundamental_service._synthesize_dynamic_protocol_milestones(now)
        self.assertGreaterEqual(len(milestones), 4)
        for m in milestones:
            self.assertIn("symbols", m)
            self.assertIn("date_event", m)
            dt_ev = parse_event_datetime(m["date_event"])
            self.assertIsNotNone(dt_ev)
            self.assertGreater(dt_ev, now, "Milestone date must be in future!")

        # Simulate CoinMarketCal API + RSS complete 429 outage
        from unittest.mock import patch, MagicMock
        with patch.object(fundamental_service.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 429
            mock_get.return_value = mock_resp

            events = fundamental_service.fetch_coinmarketcal_events(force=True)
            self.assertGreater(len(events), 0, "Must never stall; fallback schedule must engage!")
            for ev in events:
                self.assertIn("symbols", ev)
                self.assertIn("title", ev)
                self.assertIn("date_event", ev)

    def test_extended_partition_survivability_up_to_168_hours(self):
        """
        Verify that network partitions lasting >72 hours up to 168 hours (7 days)
        retain real historical records with continuous exponential time-decay and archive flag.
        """
        now = datetime.now(timezone.utc)
        article_100h = {
            "title": "Extended Partition Resilience Test Milestone for Ethereum",
            "url": "https://test-archive.com/eth-100h",
            "source": "Historical Sentinel",
            "published_at": (now - timedelta(hours=100)).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "age_hours": 100.0,
            "currencies": ["ETH"],
            "sentiment_score": 0.90,
            "sentiment_label": "🟢 BULLISH",
            "is_high_severity": False
        }
        article_200h = {
            "title": "Ancient Out-Of-Scope Milestone",
            "url": "https://test-archive.com/ancient",
            "source": "Ancient Archive",
            "published_at": (now - timedelta(hours=200)).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "age_hours": 200.0,
            "currencies": ["BTC"],
            "sentiment_score": 0.80,
            "sentiment_label": "🟢 BULLISH",
            "is_high_severity": False
        }

        # Save both to archive
        fundamental_service._save_news_archive([article_100h, article_200h])

        # Load archive at current time
        restored = fundamental_service._load_news_archive(now)

        # 100h article must survive (<= 168h) and be marked as historical
        eth_art = next((a for a in restored if a.get("title") == article_100h["title"]), None)
        self.assertIsNotNone(eth_art, "Articles between 72h and 168h must survive in extended archive!")
        self.assertTrue(eth_art.get("is_archived_historical"), "Article > 72h must have is_archived_historical=True")
        self.assertAlmostEqual(eth_art["age_hours"], 100.0, delta=0.5)

        # Mathematical decay check: 0.90 * exp(-0.025 * 100) = 0.90 * 0.08208 = ~0.07
        expected_decayed = round(0.90 * math.exp(-0.025 * 100.0), 2)
        self.assertEqual(eth_art["sentiment_score"], expected_decayed)

        # 200h article must be pruned (> 168h)
        ancient_art = next((a for a in restored if a.get("title") == article_200h["title"]), None)
        self.assertIsNone(ancient_art, "Articles older than 168h (7 days) must be cleanly pruned!")

    def test_fear_and_greed_circuit_breaker_and_secondary_sentiment(self):
        """
        Verify that Alternative.me rate-limiting trips the domain circuit breaker,
        engages secondary real-time Binance market sentiment, and restores from disk cache.
        """
        domain = "api.alternative.me"
        fundamental_service._record_success(domain)

        # Save a known durable disk cache fixture
        fng_disk_fixture = {
            "score": 68,
            "score_normalized": 0.68,
            "classification": "Greed",
            "avg_7d": 65.0,
            "trend": "EXPANDING_GREED",
            "tactical_stance": "GREED_MOMENTUM",
            "directive": "Bullish Expansion.",
            "sizing_multiplier": 1.05,
            "updated_at_utc": "2026-10-25 00:00:00 UTC",
            "source": "Historical Test Snapshot"
        }
        fundamental_service._save_fear_greed_archive(fng_disk_fixture)

        # Verify disk loading
        loaded = fundamental_service._load_fear_greed_archive()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["score"], 68)

        # Simulate Alternative.me 429 rate limit
        from unittest.mock import patch, MagicMock
        with patch.object(fundamental_service.session, "get") as mock_get:
            def side_effect(url, **kwargs):
                resp = MagicMock()
                if "alternative.me" in url:
                    resp.status_code = 429
                elif "binance.com" in url:
                    resp.status_code = 200
                    resp.json.return_value = {"priceChangePercent": "4.20"}
                return resp
            mock_get.side_effect = side_effect

            # Clear memory cache to force fallback logic
            fundamental_service._fear_greed_cache = None

            res = fundamental_service.fetch_fear_and_greed(force=True)
            self.assertTrue(fundamental_service._is_circuit_open(domain), "Alternative.me circuit must be OPEN")
            self.assertIn("Binance", res["source"], "Must fallback to secondary Binance market sentiment!")
            self.assertEqual(res["classification"], "Greed")
            self.assertGreaterEqual(res["score"], 60)

    def test_macro_ntz_expansion_readiness_and_transition(self):
        """
        Verify Macro NTZ state correctly tracks expansion readiness in compression
        and automatically unlocks Grade A+ signals when expansion triggers.
        """
        from app.engine.scanner.btc_shield import BtcPredictiveMarketShield
        shield = BtcPredictiveMarketShield()

        # 1. Simulate compression state (ADX 16.5, BBW %ile 1)
        mock_eval_squeeze = {
            "regime": "SQUEEZE",
            "probabilities": {"bull": 0.10, "bear": 0.10, "range": 0.80},
            "confidence": 0.85,
            "sizing_multiplier": 0.5,
            "metrics": {
                "adx": 16.5,
                "bb_width_percentile": 1.0,
                "rsi": 48.0
            }
        }
        with unittest.mock.patch("app.quant_v16.regime.compute_live_btc_regime", return_value=mock_eval_squeeze):
            dates = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq="15min")
            df_btc = pd.DataFrame({
                "timestamp": [int(d.timestamp() * 1000) for d in dates],
                "open": [65000.0] * 50,
                "high": [65100.0] * 50,
                "low": [64900.0] * 50,
                "close": [65000.0] * 50,
                "volume": [500.0] * 50
            })
            state_sq = shield.evaluate_regime({"15m": df_btc, "1h": df_btc, "4h": df_btc})

            self.assertTrue(state_sq["is_ntz_active"])
            self.assertEqual(state_sq["status_code"], "NO_TRADE_ZONE")
            readiness = state_sq.get("expansion_readiness", {})
            self.assertEqual(readiness["adx_current"], 16.5)
            self.assertEqual(readiness["adx_gap_to_expansion"], 3.5)
            self.assertFalse(readiness["is_expansion_imminent"])

        # 2. Simulate expansion transition (ADX 24.5, BBW %ile 40 -> BULL_TREND)
        mock_eval_expansion = {
            "regime": "BULL_TREND",
            "probabilities": {"bull": 0.75, "bear": 0.10, "range": 0.15},
            "confidence": 0.90,
            "sizing_multiplier": 1.15,
            "metrics": {
                "adx": 24.5,
                "bb_width_percentile": 40.0,
                "rsi": 62.0
            }
        }
        with unittest.mock.patch("app.quant_v16.regime.compute_live_btc_regime", return_value=mock_eval_expansion):
            state_exp = shield.evaluate_regime({"15m": df_btc, "1h": df_btc, "4h": df_btc})
            self.assertFalse(state_exp["is_ntz_active"], "NTZ must DEACTIVATE on market expansion!")
            self.assertEqual(state_exp["status_code"], "BULL_TREND")
            self.assertTrue(state_exp["altcoin_longs_allowed"])


if __name__ == "__main__":
    unittest.main()
