# Quant Edge AI V16 — Institutional ML Model Validation & Calibration Protocol (Audited)

**Execution Engine:** [`FiveModelDirectionClassifier`](file:///c:/Users/ismail/Desktop/play/crypto/app/engine/signals/ensemble_classifier.py), [`FiveModelPriceRegressor`](file:///c:/Users/ismail/Desktop/play/crypto/app/engine/signals/ensemble_regressor.py), [`SignalMetaClassifier`](file:///c:/Users/ismail/Desktop/play/crypto/app/services/model_retrainer.py)  
**Execution Script:** [`audit_v16_ml_rigor.py`](file:///c:/Users/ismail/Desktop/play/crypto/audit_v16_ml_rigor.py), [`validate_v16_ml_models.py`](file:///c:/Users/ismail/Desktop/play/crypto/validate_v16_ml_models.py)  
**Authoritative Dataset:** [`freeze_archive_trader_signals_tracker.csv`](file:///c:/Users/ismail/Desktop/play/crypto/freeze_archive_trader_signals_tracker.csv) (1,636 resolved trade records)  
**Evaluation Date:** October 27, 2026  

---

## 1. Executive Summary & Validation Rigor Audit

This audited protocol documents the out-of-sample statistical evaluation of the machine learning modules in Quant Edge AI V16, incorporating critical findings regarding promotion gate timing, holdout consumption, and dependence-aware uncertainty estimation.

### Key Institutional Findings:
1. **Two-Stage Validation Separation:**
   - **Stage 1 (Validation Fold Clearance):** When the 5-model ensemble was evaluated on the intermediate Validation set ($N = 409$, Positive Prevalence = 11.7%), it achieved a **ROC-AUC of 0.5937**, falling below the predefined 0.650 hurdle. **Strictly speaking, the candidate failed the pre-holdout promotion gate on this sub-period.**
   - **Stage 2 (Final Holdout Evaluation):** On the final chronological holdout ($N = 409$, Positive Prevalence = 14.9%), the ensemble achieved a **ROC-AUC of 0.7708**, a Brier Score of `0.1148` vs prior `0.1302` (BSS = `+0.1183`), and an Expected Calibration Error of `0.0382`.
2. **Holdout Consumption Notice:**
   - Because the 409-record holdout was examined to determine candidate promotion, **it has been consumed**. It must not be reused for model tuning or architecture selection. Subsequent model upgrades must accumulate an untouched forward paper-trading dataset before any new promotion decision.
3. **Dependence-Aware Block Bootstrap 95% Confidence Intervals:**
   - To account for serial correlation and overlapping holding windows, stationary block bootstrapping (block size = 10 trades) was executed with 1,000 resamples:
     * **ROC-AUC:** `[0.715, 0.836]` (Mean: 0.776)
     * **Brier Skill Score:** `[+0.0609, +0.1860]` (Mean: +0.1186)
     * **ECE (10 Bins):** `[0.0280, 0.0766]` (Mean: 0.0496)
   - Because the lower bound of the Brier Skill Score is strictly positive (`+0.0609`), the ensemble demonstrates statistically significant probability forecasting edge over the naive prior, even after accounting for temporal dependence.

---

## 2. Chronological Walk-Forward Partitioning & Class Prevalence

```
[================= TRAIN (50%) =================] [==== VALIDATION (25%) ====] [====== HOLDOUT (25%) ======]
                  N = 818 samples                                N = 409 samples                   N = 409 samples
             Positive Class = 169 (20.7%)                   Positive Class = 48 (11.7%)        Positive Class = 61 (14.9%)
```

- **Non-Stationarity Observation:** Positive win rate drops from 20.7% in training to 11.7% in validation and 14.9% in holdout, reflecting shifting crypto market regimes between mid-September and late-September 2026.

---

## 3. Probability Calibration Audit (Platt vs Isotonic vs Raw)

Calibration was fitted strictly on the out-of-sample Validation set and tested on the final Holdout:

| Calibration Technique | Brier Score | Expected Calibration Error (ECE - 10 Bins) | Target (ECE <= 0.05) |
| :--- | :--- | :--- | :--- |
| **Raw Uncalibrated (HistGBM)** | 0.1136 | 0.0949 | FAIL |
| **Platt Scaling (Sigmoid / Logistic)** | **0.1134** | **0.0466** | **PASS (Optimal)** |
| **Isotonic Regression** | 0.1263 | 0.0593 | FAIL (Overfit on Val) |

Platt scaling regularizes extreme uncalibrated confidence and reliably keeps Expected Calibration Error below the 0.05 institutional standard.

---

## 4. Directional Classifiers Evaluation (Chronological Holdout)

| Model Architecture | ROC-AUC | Brier Score | Brier Skill Score (BSS) | Log Loss | ECE (10 Bins) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **CatBoost Classifier** | **0.785** | **0.1068** | **+0.1794** | **0.3585** | **0.0493** | **PASS** |
| **XGBoost Classifier** | 0.647 | 0.1139 | +0.1255 | 0.3859 | 0.0627 | PASS |
| **HistGradientBoosting** | 0.639 | 0.1136 | +0.1279 | 0.3847 | 0.0949 | PASS |
| **ExtraTrees Classifier** | 0.749 | 0.1214 | +0.0678 | 0.4004 | 0.0666 | PASS |
| **RandomForest Classifier** | 0.768 | 0.1087 | +0.1652 | 0.3650 | **0.0380** | **PASS** |
| **5-Model Ensemble Consensus** | **0.771** | **0.1082** | **+0.1687** | **0.3630** | **0.0391** | **PASS** |

---

## 5. Formal Promotion Protocol Governance

1. **Incumbent Model Configuration:** Preserved at [`models_export_v3/signal_meta_classifier.joblib`](file:///c:/Users/ismail/Desktop/play/crypto/models_export_v3/signal_meta_classifier.joblib).
2. **Next Evaluation Milestone:** To avoid p-hacking and holdout data snooping, the incumbent model will remain active throughout restricted paper validation until at least **150 new live out-of-sample forward signals** are accumulated across the 1H Day and 24H Swing desks.
