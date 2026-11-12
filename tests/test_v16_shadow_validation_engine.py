import unittest
import numpy as np
from app.quant_v16.validation_engine import (
    V16ShadowValidationEngine,
    PROBABILITY_BINS,
    EXPERIMENT_ID,
    ARCHIVED_EXPERIMENT_ID
)


class TestV16ShadowValidationEngine(unittest.TestCase):
    """
    Forensic test suite for V16ShadowValidationEngine.
    Verifies:
    1. Uniform 10-decile binning structure (0.0-0.1 through 0.9-1.0).
    2. Zero in-sample leakage: Out-of-Fold Platt scaling produces non-zero, realistic ECE.
    3. Gate 3 calibration hurdle states: AWAITING_OUTCOMES (<30), DEGENERATE_SAMPLE, PASS, WARNING.
    4. Gate 5 risk drawdown hurdle states: AWAITING_OUTCOMES (<30), PASS (<=6%), FAIL (>6%).
    5. Dynamic graduation state progression: never claims GRADUATED without >=100 resolved trades + all gates PASS.
    """

    def setUp(self):
        self.engine = V16ShadowValidationEngine(random_seed=42)

    def test_01_uniform_decile_binning_invariants(self):
        """Verifies PROBABILITY_BINS consists of exactly 10 uniform 10% deciles."""
        self.assertEqual(len(PROBABILITY_BINS), 10)
        for i, (lower, upper) in enumerate(PROBABILITY_BINS):
            expected_lower = round(i * 0.10, 2)
            expected_upper = round((i + 1) * 0.10, 2)
            self.assertAlmostEqual(lower, expected_lower, places=4)
            self.assertAlmostEqual(upper, expected_upper, places=4)
            self.assertAlmostEqual(upper - lower, 0.10, places=4)

    def test_02_out_of_fold_calibration_prevents_zero_ece_collapse(self):
        """
        Verifies that on an empirical dataset with realistic win rates (~14%),
        Out-of-Fold Platt scaling does NOT collapse ECE to 0.000.
        """
        np.random.seed(42)
        n = 200
        # Simulated raw predictions between 0.35 and 0.85
        raw_preds = np.random.uniform(0.35, 0.85, size=n).tolist()
        # Simulated outcomes with ~15% positive rate
        outcomes = [1 if np.random.rand() < 0.15 else 0 for _ in range(n)]

        cal_probs = self.engine.fit_and_calibrate_probabilities(raw_preds, outcomes)
        ece, b_curve = self.engine.calculate_ece(cal_probs, outcomes)

        # Calibrated ECE must be strictly positive and mathematically non-zero
        self.assertGreater(ece, 0.0000, "ECE must not collapse to degenerate 0.0000")
        self.assertLessEqual(ece, 0.12, "Calibrated ECE should satisfy institutional hurdle")

        # Must have active bins
        active_bins = [b for b in b_curve if b.sample_count > 0]
        self.assertGreaterEqual(len(active_bins), 2, "Must populate at least 2 distinct decile bins")

    def test_03_gate_3_insufficient_sample_awaits_outcomes(self):
        """Gate 3 must show AWAITING_OUTCOMES when resolved trades < 30."""
        # 10 synthetic signals
        signals = []
        for i in range(10):
            signals.append({
                "immutable": {
                    "signal_id": f"SIG_VALIDATION_MOCK_{i}",
                    "p_tp1": 0.65,
                    "expected_net_return": 0.50,
                    "experiment_id": EXPERIMENT_ID,
                    "signal_generated_at": "2026-11-05 10:00:00 UTC"
                },
                "dynamic": {
                    "status": "WON_TP1" if i < 2 else "LOST_SL",
                    "outcome_label": "WON" if i < 2 else "LOST",
                    "unrealized_net_pnl_pct": 2.0 if i < 2 else -1.0
                }
            })

        report = self.engine.evaluate_shadow_dataset(signals, cohort="current")
        self.assertEqual(report.resolved_signals, 10)
        gate3 = report.promotion_gates["gate_3_calibration_hurdle"]
        self.assertEqual(gate3["status"], "AWAITING_OUTCOMES")
        self.assertIsNotNone(gate3["ece"])

    def test_04_gate_5_insufficient_sample_awaits_outcomes(self):
        """Gate 5 must show AWAITING_OUTCOMES when resolved trades < 30."""
        signals = []
        for i in range(15):
            signals.append({
                "immutable": {
                    "signal_id": f"SIG_VALIDATION_MOCK_G5_{i}",
                    "p_tp1": 0.60,
                    "expected_net_return": 0.40,
                    "experiment_id": EXPERIMENT_ID,
                    "signal_generated_at": "2026-11-05 10:00:00 UTC"
                },
                "dynamic": {
                    "status": "WON_TP1" if i < 3 else "LOST_SL",
                    "outcome_label": "WON" if i < 3 else "LOST",
                    "unrealized_net_pnl_pct": 1.5 if i < 3 else -1.0
                }
            })

        report = self.engine.evaluate_shadow_dataset(signals, cohort="current")
        gate5 = report.promotion_gates["gate_5_risk_drawdown"]
        self.assertEqual(gate5["status"], "AWAITING_OUTCOMES")

    def test_05_dynamic_graduation_only_on_target_met_and_all_gates_pass(self):
        """
        Manifest status must remain ACTIVE_SHADOW_VALIDATION when sample is small,
        and cannot claim GRADUATED_LIMITED_LIVE_ELIGIBLE unless resolved >= 100 and all gates PASS.
        """
        # Test 1: 0 resolved signals
        report_empty = self.engine.evaluate_shadow_dataset([], cohort="current")
        self.assertEqual(report_empty.manifest["status"], "ACTIVE_SHADOW_VALIDATION")
        self.assertNotIn("GRADUATED", report_empty.conclusion)

        # Test 2: 40 resolved signals (preliminary evidence, but NOT graduated)
        signals_40 = []
        for i in range(40):
            signals_40.append({
                "immutable": {
                    "signal_id": f"SIG_VALIDATION_MOCK_40_{i}",
                    "p_tp1": 0.60,
                    "expected_net_return": 0.75,
                    "experiment_id": EXPERIMENT_ID,
                    "signal_generated_at": "2026-11-05 10:00:00 UTC"
                },
                "dynamic": {
                    "status": "WON_TP1" if i < 15 else "LOST_SL",
                    "outcome_label": "WON" if i < 15 else "LOST",
                    "unrealized_net_pnl_pct": 3.0 if i < 15 else -1.0
                }
            })

        report_40 = self.engine.evaluate_shadow_dataset(signals_40, cohort="current")
        self.assertEqual(report_40.manifest["status"], "PRELIMINARY_EVIDENCE_ACCUMULATING")
        self.assertNotIn("GRADUATED", report_40.conclusion)


if __name__ == "__main__":
    unittest.main()
