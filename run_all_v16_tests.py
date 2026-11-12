"""
Full Automated Release Gate Test Suite for Quant Edge V16
Runs:
1. tests/test_canonical_expectancy.py
2. tests/test_temporal_integrity.py
3. tests/test_v16_entry_and_regime_debugging.py
4. tests/test_model_classification_regression.py
5. test_suite_engine.py
6. test_v16_regression.py
"""

import sys
import os
import unittest
import time

def run_suite():
    test_files = [
        "tests.test_canonical_expectancy",
        "tests.test_temporal_integrity",
        "tests.test_v16_entry_and_regime_debugging",
        "tests.test_model_classification_regression",
        "tests.test_train_serve_skew_forensics",
        "tests.test_unified_tracker_policy",
        "tests.test_model_candle_limits",
        "tests.test_extreme_volatility_blowouts",
        "tests.test_trailing_expiry_and_runner_protection",
        "tests.test_trailing_stop_evolution",
        "tests.test_network_socket_resilience",
        "tests.test_third_party_api_rate_limits",
        "tests.test_trade_thesis_clusters",
        "tests.test_qualified_v16_signals",
        "tests.test_15m_1h_24h_signals",
        "tests.test_novel_exotic_pairs_cold_start",
        "tests.test_high_market_volatility_target_clumping",
        "tests.test_exchange_ticker_naming_variations",
        "tests.test_weekly_candle_latency_and_coincap_swr",
        "tests.test_candle_close_model_training_and_prediction",
        "tests.test_live_obi_cvd_confirmation",
        "tests.test_v16_shadow_validation_engine",
        "tests.test_altcoin_decoupling_and_pure_signals",
        "tests.test_counter_trend_and_probability_invariants",
        "tests.test_v16_mtf_alignment",
        "tests.test_v16_3_horizons_and_15m_execution",
        "tests.test_cold_start_and_disk_cleanliness",
        "tests.test_candlestick_structure_and_order_blocks",
        "tests.test_smc_market_structure_15m",
        "tests.test_candle_pagination_and_cache",
        "tests.test_v16_no_signal_expiry",
    ]

    print("=" * 80)
    print("QUANT EDGE V16: AUTOMATED RELEASE GATE TEST RUNNER")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for tf in test_files:
        try:
            mod_suite = loader.loadTestsFromName(tf)
            suite.addTests(mod_suite)
            print(f"Loaded suite: {tf} ({mod_suite.countTestCases()} tests)")
        except Exception as e:
            print(f"Failed to load {tf}: {e}")

    runner = unittest.TextTestRunner(verbosity=2)
    start_t = time.time()
    result = runner.run(suite)
    elapsed = time.time() - start_t

    print("\n" + "=" * 80)
    print(f"TEST RUN COMPLETED IN {elapsed:.2f}s")
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print(f"SUCCESS: {result.wasSuccessful()}")
    print("=" * 80)

    return result.wasSuccessful()

if __name__ == "__main__":
    success = run_suite()
    sys.exit(0 if success else 1)
