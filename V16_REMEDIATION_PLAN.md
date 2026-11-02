# Quant Edge AI V16: Remediation & Execution Plan (`V16_REMEDIATION_PLAN.md`)

**Date**: 2026-10-27  
**Lead Quantitative Engineer**: Quantitative Software & ML Validation Specialist  
**Governing Standard**: Quant Edge AI V16 Accuracy-First Engineering Rules  
**Baseline Reference**: [`V16_AUDIT_BASELINE.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_AUDIT_BASELINE.md)

---

## 1. Overview & Phased Roadmap

This remediation plan translates the empirical findings from [`V16_AUDIT_BASELINE.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_AUDIT_BASELINE.md) into concrete, staged engineering implementations. Changes are executed in strict dependency order, accompanied by deterministic unit tests and out-of-sample statistical validation.

```
Phase 1 (Audit Baseline) ✅ 
   └─► Phase 2 (Expectancy & Financial Accounting) ⏳ In Progress
         └─► Phase 3 (Temporal Integrity & Barrier Ordering)
               └─► Phase 4 (ML Validation & Candidate Promotion)
                     └─► Phase 5 (Portfolio Execution Backtest)
                           └─► Phase 6 (Release Gates & Final Decision)
```

---

## 2. Phase 2: Correct Expectancy & Financial Accounting Engine

### Target Deficiencies:
- **DEF-01**: Breakeven stop-outs recorded as `WON_TIER0_BE` and counted as wins.
- **DEF-02**: Win rate denominator excluding breakeven trades (`won / (won + lost)`).
- **DEF-03**: Theoretical expectancy formula calculating multi-tranche returns (50/30/20) while execution liquidates 100% at TP1.
- **DEF-04**: Omission of spread, slippage, and funding drag in paper trading realized PnL.

### Concrete Implementation Tasks:
1. **Canonical Unit System for Expectancy**:
   - Explicitly define:
     - **Return on Position Notional** ($\%_{\text{notional}}$): The percentage price return relative to entry price.
     - **Monetary Payoff** ($\$_{\text{cash}}$): Dollar return after position sizing ($P_{\text{size}} \times \text{Return}_{\text{notional}} - \text{Total Friction}_{\$}$).
     - **Return on Capital** ($\%_{\text{capital}}$): Payoff relative to allocated desk margin.
   - Forbid combining dimensionless reward-to-risk ratios with percentage costs without explicit unit conversion.

2. **Refactored `CanonicalExpectancyEngine`** ([`app/quant_v16/expectancy.py`](file:///c:/Users/ismail/Desktop/play/crypto/app/quant_v16/expectancy.py)):
   - Unify single-target and multi-target calculation modes:
     - Single-target (TP1 100% exit policy):
       $$EV_{\text{gross}} = P(\text{TP1}) \cdot r_1 - (1 - P(\text{TP1})) \cdot r_{\text{sl}}$$
       $$EV_{\text{net}} = EV_{\text{gross}} - \text{Total Friction}_{\%}$$
     - Multi-tranche (Scaling policy):
       Include the probability of reaching TP1 and subsequently stopping out at Breakeven ($r = 0 - \text{Exit Fee}$), eliminating the fictitious zero-loss assumption on tranches 2 and 3.
   - Comprehensive friction deduction:
     $$\text{Total Friction}_{\%} = \text{Fee}_{\text{entry}} + \text{Fee}_{\text{exit}} + \text{Spread}_{\text{entry}} + \text{Spread}_{\text{exit}} + \text{Slippage} + \text{Funding}$$

3. **Accounting Corrections**:
   - In [`app/services/signal_service.py`](file:///c:/Users/ismail/Desktop/play/crypto/app/services/signal_service.py):
     - Replace `s.status = "WON_TIER0_BE"` with `s.status = "BREAKEVEN_GUARD"` and `s.outcome_label = f"🛡️ BREAKEVEN ({ret_pct:+.2f}%)"`.
   - In [`app/models/signal.py`](file:///c:/Users/ismail/Desktop/play/crypto/app/models/signal.py):
     - Map `"BREAKEVEN"` to `outcome = "BREAKEVEN"` (never `"WON"`).
   - In [`app/routers/portfolio.py`](file:///c:/Users/ismail/Desktop/play/crypto/app/routers/portfolio.py):
     - Set `total_decisive = won + lost + be` and compute:
       $$\text{win\_rate\_pct} = \frac{\text{won}}{\text{won} + \text{lost} + \text{be}} \times 100.0$$
   - In [`app/engine/execution/paper_trading_bot.py`](file:///c:/Users/ismail/Desktop/play/crypto/app/engine/execution/paper_trading_bot.py):
     - Deduct spread crossing ($0.5 \times \text{Spread}_{\text{bps}}$), slippage ($4 \text{ bps}$), and accrued funding rate in realized PnL calculations.

4. **Deterministic Unit Tests**:
   - Create [`tests/test_canonical_expectancy.py`](file:///c:/Users/ismail/Desktop/play/crypto/tests/test_canonical_expectancy.py) testing zero-cost, known-cost, breakeven stop-outs, fee + slippage accounting, and exact grade boundaries.

---

## 3. Phase 3: Enforce Temporal Integrity & Barrier Ordering

### Target Deficiencies:
- **DEF-05**: Intrabar/intrawindow path ambiguity in `TripleBarrierLabeler`.

### Concrete Implementation Tasks:
1. **Sequential Bar Event Traversal**:
   - Rewrite `TripleBarrierLabeler.apply_barriers` to iterate candle-by-candle within the horizon window rather than using decoupled rolling max/min.
   - If candle $t+k$ touches $SL$ prior to candle $t+m$ touching $TP$ ($k \le m$), strictly record `outcome = 0` (LOSS).
   - If both barriers are touched in the exact same candle $t+k$, enforce adverse stop-loss precedence ($SL < TP$).
2. **Feature Lookahead Verification**:
   - Audit all rolling/EWM indicators in `AdvancedFeatureEngineer` to ensure `shift(1)` is enforced on all cross-timeframe merged features.
3. **Future Mutation Unit Tests**:
   - Create `tests/test_temporal_integrity.py` asserting that modifying future data does not alter predictions or decisions at timestamp $T$.

---

## 4. Phase 4: ML Model Validation & Promotion Gates

### Target Deficiencies:
- **DEF-06**: Heuristic hardcoded conditional path probabilities.
- **DEF-07**: Regressor target trained on peak MFE.
- **DEF-08**: Sample sufficiency conflated with 15-candle data readiness.

### Concrete Implementation Tasks:
1. **Statistically Defensible Sample Sufficiency**:
   - Require $N \ge 60$ historical candles before activating 5-model ML ensemble fitting.
   - Maintain cold-start Laplace regularized prior during $N < 60$.
2. **Regressor Target Refactoring**:
   - Train regressors on actual realization target (e.g. exit return or close return) rather than peak unachievable MFE.
3. **Model Promotion Gate**:
   - Train candidate models alongside incumbent models. Only promote candidate if out-of-sample Brier Skill Score $> 0$ and Log Loss improves over incumbent.

---

## 5. Phase 5: Portfolio Validation & Dual-Mode Stress Pipeline

### Concrete Implementation Tasks:
1. **Realistic Multi-Desk Backtest Simulation** ([`app/quant_v16/backtest.py`](file:///c:/Users/ismail/Desktop/play/crypto/app/quant_v16/backtest.py)):
   - Shared capital model ($1,000 initial equity).
   - Multi-desk slot allocation: Scalp (35%, 2 slots, 5x leverage), Day (40%, 2 slots, 3x leverage), Swing (25%, 1 slot, 2x leverage).
   - Itemized friction: taker fees (0.0405%), bid-ask spread crossing (4.0 bps), execution slippage (3.0 bps), pro-rated 8h funding drag (0.01%).
2. **Dual Simulation Modes**:
   - `FROZEN_NOTIONAL_SENSITIVITY`: Fixed baseline position size per trade across all scenarios, isolating pure execution friction sensitivity (Gross PnL mathematically invariant at $1,270.08).
   - `DYNAMIC_COMPOUNDING`: Dynamic compounding where equity drawdowns scale down subsequent trade position sizes.
3. **Exact Accounting Reconciliation (DEF-09)**:
   - Consistent 2-decimal per-trade rounding: $\text{net\_pnl\_usd} = \text{gross\_pnl\_usd} - \text{total\_friction\_usd}$.
   - Guarantees $\sum \text{gross} - \sum \text{friction} == \sum \text{net}$ down to $0.00 discrepancy.
4. **Canonical Desk Resolution (DEF-10)**:
   - Check multi-day/macro identifiers first (`24H`, `1D`, `4D`, `7D`, `15D`, `30D` $\to$ Swing Desk) to prevent `15D` from matching `15M`.

---

## 6. Phase 6: Restricted Paper Validation Protocols

1. **Horizon Prioritization**:
   - Live real-money trading strictly disabled.
   - Forward paper validation restricted to **1H Day Desk** and **24H Swing Desk**.
   - 15M Scalp Desk halted due to high-frequency execution friction.
2. **Trade Logging Standards**:
   - Record decision and feature timestamps, model versions, predicted win probabilities, intended vs executed prices, itemized frictions, position sizing, and exit reasons.
3. **Predeclared Evaluation Hurdles**:
   - Minimum duration: 30 calendar days.
   - Minimum sample size: 150 independent trades.
   - Outlier resilience requirement: Strategy must remain profitable without the top 3 outlier trades.

---

## 7. Deliverable Artifact Tracking

- [x] [`V16_AUDIT_BASELINE.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_AUDIT_BASELINE.md) — Baseline defect audit and verified architecture.
- [x] [`V16_REMEDIATION_PLAN.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_REMEDIATION_PLAN.md) — Step-by-step phased engineering roadmap.
- [x] [`V16_VALIDATION_PROTOCOL.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_VALIDATION_PROTOCOL.md) — Audited ML validation protocol, holdout consumption notice, and block bootstrap CIs.
- [x] [`V16_TEST_RESULTS.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_TEST_RESULTS.md) — Full 105-test automated release gate execution results.
- [x] [`V16_BACKTEST_REPORT.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_BACKTEST_REPORT.md) — Reconciled backtest report with Frozen Notional and Dynamic Compounding evaluations.
- [x] [`V16_RELEASE_DECISION.md`](file:///c:/Users/ismail/Desktop/play/crypto/V16_RELEASE_DECISION.md) — Formal release decision and governance sign-off.
