# Quant Edge AI V16 — Engineering & Coding Guidelines (`AGENTS.md`)

This document defines the mandatory operating protocols, architectural invariants, performance standards, and coding rules for all AI coding agents and quantitative engineers working in this repository.

---

## 1. Non-Negotiable Core Principles

1. **Correctness Over Speed**: Code correctness and mathematical integrity always take precedence over rapid implementation. Never rush a patch at the expense of systemic stability.
2. **Evidence-Based Engineering**:
   - Never invent files, facts, APIs, configurations, logs, test results, or system behavior.
   - Treat all assumptions as hypotheses until confirmed by inspecting source code, test execution, or runtime data.
   - Never claim a task or test passed without executing the command and inspecting the output.
3. **Always Dynamic Code (Zero Hardcoding Policy)**:
   - **No Hardcoded Values**: Never hardcode prices, probabilities, coin parameters, leverage multipliers, dates, thresholds, or outcome strings.
   - **Dynamic Context**: All logic must adapt dynamically based on market regime (ATR volatility, ADX trend strength), calibrated model outputs, database states, and environment configurations.
   - **Dynamic Fallback Chains**: Never fabricate synthetic data in place of missing market information. Engage the dynamic multi-exchange fallback hierarchy (`Binance` $\to$ `Bybit` $\to$ `OKX` $\to$ `Gate.io` $\to$ `KuCoin` $\to$ `MEXC` $\to$ `CoinCap` $\to$ `SWR Cache`) and fail closed when data quality is insufficient.
4. **Full System Alignment**:
   The following modules must remain strictly synchronized with zero data discrepancies:
   - **Quant Edge V16 Institutional Terminal** (Next.js frontend)
   - **Live Top 40 Quantitative Scanner Matrix** (Scanner daemon)
   - **Multi-Horizon Matrix** (`5M`, `15M`, `1H`, `4H`, `12H`, `24H`, `7D`, `15D`, `1M`)
   - **Trader Signals Audit Ledger** (`signals_tracker`, `closed_trades`)
   - **Active Paper Trading Bot & Ledger** (`paper_trading_ledger.json`)
   - **WhatsApp Broadcast Dispatch** (Evolution API / Baileys Gateway)
5. **No Clutter & Clean Repository Discipline**:
   - Do **NOT** create ad-hoc scratch scripts, debug dumps, or temporary CSV/JSON files in the project root.
   - Authoritative state data belongs strictly in `export_app_data/`.
   - Ephemeral test files belong strictly in `scratch/` (which is gitignored).
6. **Complete Deliverables Only (Zero Placeholders)**:
   - Deliver 100% complete, fully implemented, drop-in replacement code.
   - Strictly prohibit ellipses (`...`), `# TODO`, `# insert implementation here`, truncated functions, missing error handlers, or half-implemented features.
   - Every file modified must be immediately runnable and end-to-end operational.

---

## 2. Non-Regression & Blast-Radius Containment

Modifying existing code or introducing new features must **never** degrade or break existing features. Every code change must enforce strict blast-radius containment:

### 2.1 Caller & Dependent Trace Before Editing
Before editing any function, class, route, or model:
1. Identify all callers and dependents across the entire repository (`git grep` or AST trace).
2. Trace the data flow across API contracts, frontend hooks, database sync, and WebSocket events.
3. Ensure that modifying a shared utility or engine function does not alter expectations in other callers.

### 2.2 Preserving Contracts & Interfaces
- **API Contracts**: Never break, rename, or remove fields in existing REST endpoint responses or WebSocket payloads. New fields must be additive and optional.
- **Database Schema Integrity**: Never alter column types, drop tables, or break migration compatibility without explicit backward-compatible fallback logic.
- **Function Signatures**: When extending existing functions, use default/optional parameters to prevent breaking existing callers.

### 2.3 Bug-Fix Isolation Principle
- Fix the **root cause** at its source rather than patching symptoms downstream.
- A bug fix in Feature A must never compromise Feature B.
- Never weaken assertions, loosen mathematical hurdles (such as $EV_{\text{net}} > 0$), or bypass risk gates to make a failing test or trade pass.
- Add an explicit regression test to verify that the bug is fixed and cannot reoccur.

---

## 3. Performance & Computational Efficiency

Quant Edge AI V16 operates as a continuous, high-frequency multi-horizon scanner. All code must be designed for maximum throughput and minimal latency:

### 3.1 Vectorized Data Processing
- Use vectorized NumPy and Pandas operations for feature calculation, indicator generation, and matrix transformations.
- Avoid row-by-row Python iteration (`for index, row in df.iterrows():`) on candle DataFrames. Prefer vectorized boolean masks, `np.where`, `rolling()`, and `apply()` only when vectorization is mathematically impossible.
- Pre-allocate arrays and data structures when sizing is known in advance.

### 3.2 In-Memory Caching & Pre-Warming
- **Model Registry Pre-Warming**: Preload ML models, scalers, and meta-classifiers into memory at daemon startup (`models_cache.joblib`, `PerCoinModelRegistry`). Never load heavy `.joblib` files from disk inside per-coin evaluation loops.
- **Fast In-Memory Lookups**: Leverage Redis for ephemeral state caching, hot ticker prices, and deduplication sets (`allkeys-lru`, 512MB quota).
- **Persistent Cache SWR**: Use stale-while-revalidate patterns for external HTTP feeds with fast-fail circuit breakers (900s for HTTP 403/451 geo-restrictions).

### 3.3 I/O, Database, & Network Discipline
- **Atomic Batch Writes**: Group database insertions into batch commits (`bulk_insert_mappings` or chunked sessions). Never execute single-row `db.commit()` inside intensive loops.
- **File I/O Optimization**: State exports to `export_app_data/` must be written atomically (`tempfile` + `os.replace`) to prevent corrupted reads by concurrent services, and throttled to state-change events rather than redundant tick rewrites.
- **Async & Non-Blocking Architecture**: FastAPI route handlers and WebSocket dispatches must never perform blocking synchronous I/O on the main event loop. Offload heavy computations to worker threads (`asyncio.to_thread` or thread pools).
- **Thread & Concurrency Constraints**: In multi-process container environments, explicitly restrict OpenMP and math libraries to 1 thread per worker (`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`) to eliminate CPU core thread thrashing.

---

## 4. Quantitative & Trading Engine Invariants

### 4.1 Financial Accounting & Friction Integrity
- **Itemized Deductions**: Net Expectancy must account for all trading frictions:
  $$\text{Total Friction} = \text{Fee}_{\text{entry}} + \text{Fee}_{\text{exit}} + \text{Spread} + \text{Slippage} + \text{Funding Drag}$$
  $$\text{Net EV} = \text{Gross EV} - \text{Total Friction}$$
- **Strict Breakeven Accounting**:
  - Breakeven trades (`WON_TIER0_BE`, `STOP_LOSS_BREAKEVEN`) must **never** be counted as wins in the audit ledger or win rate formulas.
  - The win rate formula must preserve denominator integrity:
    $$\text{Total Win Rate} = \frac{\text{Won}}{\text{Won} + \text{Lost} + \text{Breakeven}}$$
    $$\text{Decisive Win Rate} = \frac{\text{Won}}{\text{Won} + \text{Lost}}$$

### 4.2 Price Geometry & Lookahead Guard
- **Price Invariants**:
  - Long: $\text{Stop Loss} < \text{Entry} < \text{TP1} < \text{TP2} < \text{TP3}$
  - Short: $\text{Stop Loss} > \text{Entry} > \text{TP1} > \text{TP2} > \text{TP3}$
  - Zero, negative, or zero-distance values ($\text{Entry} == \text{SL}$) must fail closed and be rejected immediately.
- **Lookahead Prevention**:
  - No feature may use candle data or information unavailable at the signal generation timestamp.
  - Training sequences and evaluation windows must remain strictly chronological.
  - Unresolved outcomes in historical datasets must remain `NaN` until their horizon has fully matured.

### 4.3 Probability Coherence
- Predicted probabilities must satisfy:
  $$P(\text{TP1}) + P(\text{SL}) = 1.0$$
  $$P(\text{TP3}) \le P(\text{TP2}) \le P(\text{TP1})$$
- Raw model outputs must undergo probability calibration (e.g. Platt scaling / isotonic regression) against out-of-sample empirical outcomes.
- High model confidence does not guarantee trade profitability—every signal must pass the net expectancy hurdle ($\text{EV}_{\text{net}} > 0$).

---

## 5. Codebase Architecture & File Ownership

```
├── app/                           # FastAPI REST Backend & Trading Engine
│   ├── config.py                  # Pydantic environment settings
│   ├── database.py                # MySQL 8.0 connection & SQLite fallback
│   ├── main.py                    # App entrypoint & middleware
│   ├── engine/                    # Core scanning, SMC, features, & paper trading
│   │   ├── scanner/               # Multi-exchange data loader & BTC market shield
│   │   ├── signals/               # ML ensemble classifiers, regressors, meta-labeler
│   │   └── execution/             # Paper trading bot & tick watchers
│   ├── quant_v16/                 # V16 Math: expectancy, costs, order blocks, audit
│   ├── models/                    # SQLAlchemy database ORM models
│   ├── routers/                   # API endpoint routers (/api/v16, /api/signals, etc.)
│   └── services/                  # SignalService, DbSync, WebSocket, WhatsApp
├── frontend/                      # Next.js 14 Institutional Web Terminal
│   ├── src/app/                   # App router pages & layouts
│   ├── src/components/            # Trading tables, matrix, radar, modals
│   ├── src/hooks/                 # React Query data polling & WebSocket hooks
│   └── src/lib/                   # API client, audio alerts, market shield
├── whatsapp/                      # WhatsApp Baileys Gateway service
│   ├── package.json
│   └── server.js
├── export_app_data/               # Authoritative runtime data exports (JSON & CSV)
├── models_export_v3/              # Production ML models, cache, & per-coin models
├── tests/                         # Official Pytest test suite (10 modules)
├── nginx/                         # Reverse proxy configuration
├── scratch/                       # Temporary scratch directory (.gitkeep)
├── Dockerfile.backend             # Production backend & scanner container
├── Dockerfile.whatsapp            # Production WhatsApp gateway container
├── docker-compose.yml             # Orchestration: db, redis, backend, scanner, frontend, wa
├── deploy.sh                      # Production VPS deployment script
├── run_scanner_daemon.py          # Continuous ML prediction scanner daemon
├── run_modular_daemon.py          # Modular scanner daemon
├── train_meta_labeler.py          # Secondary meta-labeling model trainer
├── train_per_coin_models.py       # Per-coin specialized ML model trainer
├── test.py                        # Core historical calculation engine
├── run_all_v16_tests.py           # Authoritative 37-test release gate suite runner
├── test_suite_engine.py           # 43 engine unit tests
├── test_v16_regression.py         # 25 golden master regression tests
├── audit_v16_ml_rigor.py          # ML statistical rigor & calibration audit
└── audit_v16_swing_desk.py        # Swing desk performance & outlier audit
```

---

## 6. Implementation & Language Standards

### 6.1 Backend & Python Standards
- Python 3.10+ compatible code.
- Always handle missing, null, NaN, and Inf values safely (`np.nan_to_num`, explicit bounds checking).
- Avoid mutating global state or module-level variables across requests.
- When querying database models, always handle `OperationalError` and connection failovers safely via [`app/database.py`](file:///c:/Users/ismail/Desktop/play/crypto/app/database.py).
- Maintain documentation integrity: preserve docstrings and quantitative audit references.

### 6.2 Frontend & Next.js Standards
- Next.js 14 App Router conventions.
- Strict TypeScript: no unhandled `any` types that mask contract breaks.
- All data-fetching hooks must use `@tanstack/react-query` or WebSocket with fallback polling.
- Ensure all numbers, timestamps, and currency values are formatted defensively (handling undefined/null).

### 6.3 Data Persistence & State Management
- Never silently drop or discard audit records, trade events, or signals.
- All persistent exports must be written atomically (`tempfile` + `os.replace`) to prevent corrupted reads by concurrent services.
- Store runtime exports in `settings.EXPORT_DIR` ([`export_app_data/`](file:///c:/Users/ismail/Desktop/play/crypto/export_app_data)).

---

## 7. Mandatory Verification Protocol Before Submitting Code

Before claiming any task is complete, execute checks in this exact order:

1. **Targeted Regression / Unit Tests**:
   ```powershell
   python test_v16_regression.py
   python -m unittest test_suite_engine.py
   ```
   *Requirement: 25/25 regression tests and 43/43 engine unit tests must pass (68 total).*

2. **Official Release Gate Suite**:
   ```powershell
   python run_all_v16_tests.py
   ```
   *Requirement: 37/37 tests must pass.*

3. **Frontend Typecheck (if modifying frontend)**:
   ```powershell
   cd frontend; npx tsc --noEmit
   ```
   *Requirement: 0 TypeScript errors.*

4. **FastAPI Route & Initialization Verification**:
   ```powershell
   python -c "from app.main import app; from fastapi.testclient import TestClient; c = TestClient(app); assert c.get('/api/status').status_code == 200; print('Backend OK')"
   ```

5. **Docker Compose Configuration Validation**:
   ```powershell
   docker compose config --quiet
   ```
   *Requirement: Exit code 0.*

---

## 8. Response Contract for Non-Trivial Changes

For every non-trivial coding task, the final response must provide:
1. **The requested outcome**: Clear statement of the task.
2. **Confirmed root cause or architecture plan**: Specific files and lines identified.
3. **Files changed**: Exact path and reason for each change.
4. **Commands and tests executed**: Exact shell commands and their actual results.
5. **Acceptance criteria status**: Passed, skipped, or blocked (with reasons).
6. **Remaining risks or limitations**: Explicitly stated without generic assurances.
