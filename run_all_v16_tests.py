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
