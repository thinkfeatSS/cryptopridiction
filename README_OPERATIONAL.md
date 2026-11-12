# The Only 1 Minute AI Trading System — By Anees Mehdi
## Enterprise Multi-Agent Algorithmic Cryptocurrency Signal Generation & Execution Terminal

---

## 1. Executive Summary & Strategy Foundations

**The Only 1 Minute AI Trading System** is an institutional-grade, multi-agent algorithmic trading engine engineered around the original strategy documented by **Anees Mehdi** in *"The Only 1 Minute Trading Strategy You'll Ever Need"*.

### Core Operating Invariants:
1. **NO CONFIRMATION = NO TRADE**: The system prioritizes signal quality, statistical edge, and capital preservation over trade frequency. Trades are executed only when unanimous multi-timeframe and multi-agent confirmation is achieved.
2. **Continuation Trading Only**:
   - **Bullish Trend**: The system strictly focuses on pullbacks into **swing lows**, waiting for liquidity sweeps and bullish weakness (lower wick rejection). Countertrend shorting is strictly prohibited.
   - **Bearish Trend**: The system strictly focuses on rallies into **swing highs**, waiting for liquidity sweeps and bearish weakness (upper wick rejection). Countertrend buying is strictly prohibited.
3. **Exact Anees Mehdi Rectangle Mathematics**:
   The execution rectangle is constructed directly from the M15 trigger candle's rejection wick:
   - **Bullish Setup**: $\text{Lower Boundary} = \text{Trigger Candle Low}$, $\text{Upper Boundary} = \text{Trigger Candle Close}$
   - **Bearish Setup**: $\text{Lower Boundary} = \text{Trigger Candle Close}$, $\text{Upper Boundary} = \text{Trigger Candle High}$
4. **M1 Flip Execution Trigger**:
   Execution never occurs on M15 close alone. Once the rectangle is locked, the engine watches sequential closed 1-minute (M1) bars:
   - **Bullish Execution**: M1 candle must close strictly **ABOVE** the rectangle's upper boundary.
   - **Bearish Execution**: M1 candle must close strictly **BELOW** the rectangle's lower boundary.
   - **Timeout**: The setup expires after a maximum of 15 M1 bars.
5. **Mandatory 1:2.0 Net Risk-to-Reward Ratio**:
   Every setup must maintain $\ge 1:2.0$ Net RRR after itemized deductions for trading fees (0.04% each side), dynamic bid-ask spread, and market slippage.

---

## 2. Five-Agent AI Architecture

The system coordinates five specialized artificial intelligence agents running in a sequential, fast-fail pipeline:

```
[1D Candles] ---> Agent 1: Daily Market Direction Agent (Macro Context & S/R)
                        |
                        v
[4H Candles] ---> Agent 2: 4H Trend & Structure Agent (Primary Trend & BOS)  ---[Fast-Fail Exit]
                        |
                        v
[1H Candles] ---> Agent 3: 1H Market Behavior Agent (Pullback Dynamics)       ---[Fast-Fail Exit]
                        |
                        v
[15M & 1M]   ---> Agent 4: 15M Setup & 1M Execution Agent (Rectangle Flip)   ---[Fast-Fail Exit]
                        |
                        v
[Cross-Timeframe] Agent 5: Validation & Risk Gatekeeper (ML & Risk Hurdles)  ---[Fast-Fail Exit]
                        |
                        +---> [APPROVED TRADE SIGNAL & PAPER BOT EXECUTION]
```

### Agent Responsibilities:
- **Agent 1 (Daily Market Direction)**: Operates on 1D candles. Analyzes macro trend (50 & 200 EMA), major daily support & resistance, daily swing points, and daily Order Blocks. **Analysis only; never generates direct entries.**
- **Agent 2 (4H Trend & Structure)**: Operates on 4H candles. Evaluates primary market trend (Price vs 200 EMA) and market structure (Higher Highs / Higher Lows or Lower Highs / Lower Lows). Rejects ranging corridors and sideways chop.
- **Agent 3 (1H Market Behavior)**: Operates on 1H candles. Confirms that intermediate pullbacks are orderly continuation setups rather than aggressive opposing structural reversals (opposing CHoCH).
- **Agent 4 (15M Setup & 1M Execution)**: Operates on 15M and 1M candles. Identifies closed-candle Weakness sweeps, constructs the Anees Mehdi Rectangle, and monitors incoming closed M1 candles for flip confirmation outside rectangle boundaries.
- **Agent 5 (Validation & Risk Gatekeeper)**: Final gatekeeper. Verifies unanimous $4\text{H} == 1\text{H} == 15\text{M}$ directional alignment, executes ML setup quality inference ($P(\text{Win}) \ge 0.58$), runs Isolation Forest anomaly detection, checks opposing HTF Order Block POI collisions, and verifies Net RRR $\ge 1:2.0$.

---

## 3. System Architecture & Directory Tree

```
c:\Users\ismail\Desktop\play\crypto\
├── trading_ai_system/
│   ├── config/                     # Configuration, Pydantic settings & trading rules
│   │   ├── settings.py             # RAM cap (2560 MB), thread cap, logging settings
│   │   ├── trading_rules.py        # Authoritative Anees Mehdi strategy rules
│   │   └── pairs.py                # 40 utility pairs (hard exclusion of meme/leveraged tokens)
│   ├── data/                       # Market data ingestion, models & persistence
│   │   ├── models.py               # Candle, Timeframe models with price geometry invariants
│   │   ├── validator.py            # Closed-candle validator, gap and stale data detection
│   │   ├── rest_client.py          # Binance public REST client with rate-limit queue
│   │   ├── candle_buffer.py        # Multi-timeframe deque rolling cache (1d, 4h, 1h, 15m, 1m)
│   │   ├── storage.py              # SQLite WAL persistence with connection pooling
│   │   └── websocket_client.py     # Live Binance multi-stream WebSocket subscriber
│   ├── indicators/                 # Single-pass vectorized technical analysis
│   │   ├── moving_averages.py      # EMA 50, EMA 200, slope, ranging corridor detector
│   │   ├── volatility.py           # Wilder's ATR, NATR, dynamic SL buffer (0.15 * ATR)
│   │   ├── candle_geometry.py      # Body size, wick ratios, weakness rejection evaluation
│   │   ├── volume.py               # Volume SMA, RVOL, volume delta
│   │   ├── momentum.py             # Wilder's 14-period RSI with zero-division handling
│   │   └── engine.py               # Unified IndicatorEngine
│   ├── market_structure/           # Non-repainting market structure engine
│   │   ├── models.py               # SwingPoint, StructureBreak, TrendState, MarketStructureResult
│   │   ├── swing_detector.py       # Non-repainting fractal swings with right-shoulder delay
│   │   ├── structure_breaks.py     # BOS continuation & CHoCH reversal state machine
│   │   └── engine.py               # Unified MarketStructureEngine with sideways filter
│   ├── liquidity/                  # Smart money concepts liquidity & FVG
│   │   ├── models.py               # LiquidityPool, LiquiditySweepEvent, FairValueGap, SessionLevel
│   │   ├── liquidity_sweeps.py     # Weakness trigger vs Strength disrespect filter
│   │   ├── fvg_detector.py         # 3-bar displacement FVG detector and mitigation tracker
│   │   ├── session_levels.py       # Asia, London, New York session highs & lows
│   │   └── engine.py               # Unified LiquidityEngine
│   ├── order_blocks/               # Institutional Order Block engine
│   │   ├── models.py               # OrderBlock, OBType, OBState
│   │   ├── ob_detector.py          # Displacement-backed (>= 1.5x) OB preceding confirmed BOS
│   │   ├── ob_tracker.py           # Lifecycle tracker (FRESH, PARTIAL, FULL, INVALIDATED)
│   │   └── engine.py               # Unified OrderBlockEngine & HTF collision guard
│   ├── strategy/                   # Original Anees Mehdi Rectangle Strategy
│   │   ├── models.py               # Rectangle, RectangleDirection, RectangleStatus, TradeSignal
│   │   ├── rectangle_constructor.py# Exact Anees Mehdi rectangle boundary mathematics
│   │   ├── m1_flip_watcher.py      # M1 candle-close flip watcher with 15-bar timeout & SL guard
│   │   └── engine.py               # RectangleStrategyEngine & 27-field TradeSignal generator
│   ├── multi_timeframe/            # Multi-timeframe synchronization
│   │   ├── models.py               # TimeframeAnalysis, MTFAlignmentResult
│   │   ├── analyzer.py             # Single timeframe deep analyzer
│   │   ├── aligner.py              # Strict 4H == 1H == 15M consensus evaluator
│   │   └── engine.py               # Unified MultiTimeframeEngine qualification gate
│   ├── ml_engine/                  # Machine Learning setup classification
│   │   ├── feature_pipeline.py     # Standardized 24 numerical features
│   │   ├── dataset_builder.py      # Non-lookahead training dataset builder & synthetic generator
│   │   ├── models.py               # Ensemble (LR, LightGBM, XGBoost, RF) + HMM + IsolationForest
│   │   ├── trainer.py              # Sequential CPU training pipeline with probability calibration
│   │   └── predictor.py            # SetupQualityPredictor singleton with rule-based fallback
│   ├── agents/                     # Five-Agent AI Architecture
│   │   ├── models.py               # AgentVerdict, AgentDecision, FiveAgentPipelineResult
│   │   ├── agent1_daily_market.py  # Agent 1: 1D Market Direction
│   │   ├── agent2_4h_trend.py      # Agent 2: 4H Trend & Structure
│   │   ├── agent3_1h_behavior.py   # Agent 3: 1H Market Behavior
│   │   ├── agent4_setup_execution.py# Agent 4: 15M Setup & 1M Execution Trigger
│   │   ├── agent5_validation_risk.py# Agent 5: Validation & Risk Gatekeeper
│   │   └── orchestrator.py         # FiveAgentOrchestrator fast-fail pipeline
│   ├── risk/                       # Risk management & capital preservation
│   │   ├── models.py               # FrictionBreakdown, NetExpectancyResult, PositionSizingResult
│   │   ├── friction_calculator.py  # Taker fees (0.04%), spread (1.5 bps), slippage (1.5 bps)
│   │   ├── rrr_validator.py        # Strict Net RRR >= 1:2.0 validation after friction
│   │   ├── position_sizer.py       # Fixed fractional 1% sizing with leverage bounds
│   │   ├── portfolio_risk_manager.py# Concurrency (max 3), 4% daily drawdown kill-switch
│   │   └── engine.py               # Unified RiskEngine
│   ├── backtesting/                # Event-driven backtesting & multi-strategy benchmarking
│   │   ├── models.py               # BacktestTrade, BacktestReport, StrategyVersion, ExitReason
│   │   ├── trade_simulator.py      # Forward M1 simulation with adverse same-candle resolution
│   │   ├── engine.py               # EventDrivenBacktestEngine with full performance analytics
│   │   └── benchmark.py            # StrategyComparator (Version A vs Version B vs Version C)
│   ├── execution/                  # Real-time paper trading bot & ledger
│   │   ├── models.py               # PaperTrade, PaperTradeStatus
│   │   └── paper_trading_bot.py    # Automated paper trading bot with SQLite persistence
│   ├── api/                        # Institutional FastAPI REST Server
│   │   └── server.py               # Endpoints: /health, /api/signals, /api/paper-trades, /api/risk
│   ├── monitoring/                 # Hardware telemetry & rotating logging
│   │   ├── logger.py               # Rotating disk and colored console logger
│   │   └── system_monitor.py       # psutil RAM and CPU watchdog
│   ├── tests/                      # Full 71-test automated unit and integration suite (13 modules)
│   └── runner.py                   # Continuous live daemon runner
├── start_trading_system.bat        # Windows 11 one-click launcher
└── test_v16_regression.py          # 25 Golden Master regression tests
```

---

## 4. Hardware Budget & Resource Constraints

The system is strictly engineered to operate on standard commodity hardware:

| Resource | Specification | Enforced Safeguard |
|---|---|---|
| **RAM** | 8 GB Total System Memory | Process memory capped at **2,560 MB** with proactive GC |
| **CPU** | 4 Cores | Mathematical threads capped (`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`) |
| **GPU** | Not Required | All machine learning models optimized for CPU inference |
| **Paid AI APIs** | **$0.00 (Zero Dependency)** | 100% free open-source libraries (`scikit-learn`, `lightgbm`, `xgboost`, `hmmlearn`) |
| **Market Feeds** | Public Binance Endpoints | Public REST with rate-limit queue + public WebSocket streams |

---

## 5. Verification & Testing Protocol

Before running in production, execute verification in the following sequence:

### 1. Run the Full 71-Test System Suite:
```powershell
python -m unittest discover -s trading_ai_system/tests
```
*Requirement: 71/71 tests must pass.*

### 2. Run the Golden Master Forensic Regression Gate:
```powershell
python test_v16_regression.py
```
*Requirement: 25/25 tests must pass (100% mathematical integrity).*

### 3. Launch FastAPI Server & Validate Telemetry:
```powershell
python -c "from fastapi.testclient import TestClient; from trading_ai_system.api.server import app; c = TestClient(app); assert c.get('/health').status_code == 200; print('API Operational!')"
```

---

## 6. Operating Instructions

### Launching via Windows 11 Batch Script:
Double-click `start_trading_system.bat` in the project root:
```
===============================================================================
  Select an Operation Mode:
    [1] Start Live Scanner & Paper Trading Daemon (WebSocket + Five Agents)
    [2] Start Institutional FastAPI REST API Server (Port 8000)
    [3] Run Full 71-Test Automated Unit & Integration Suite
    [4] Run Golden Master 25-Test Release Gate Regression Suite
    [5] Run Multi-Strategy Backtesting Benchmark (Version A vs B vs C)
    [6] Exit
===============================================================================
```

### Starting the Live Continuous Scanner & Paper Bot:
```powershell
python -m trading_ai_system.runner
```

### Starting the FastAPI REST Server:
```powershell
uvicorn trading_ai_system.api.server:app --host 0.0.0.0 --port 8000 --reload
```

### REST API Reference:
- `GET /health` or `GET /api/status`: System status, uptime, process RAM (MB), CPU usage %, active positions count.
- `GET /api/signals`: Paginated list of generated signals with all 27 authoritative fields.
- `GET /api/paper-trades`: Real-time ledger of open and closed virtual trades with itemized net PnL.
- `GET /api/risk`: Current portfolio risk metrics, account balance, daily drawdown %, and kill-switch status.

---

## 7. Mathematical Invariants & Risk Reference

- **Itemized Total Friction**:
  $$\text{Total Friction} = \text{Fee}_{\text{entry}} (0.04\%) + \text{Fee}_{\text{exit}} (0.04\%) + \text{Spread} (0.015\%) + \text{Slippage}_{\text{entry}} (0.015\%) + \text{Slippage}_{\text{exit}} (0.015\%) = 0.125\%$$
- **Net Expectancy RRR**:
  $$\text{Net RRR} = \frac{\text{Gross Reward} - \text{Total Friction}}{\text{Gross Risk} + \text{Total Friction}} \ge 2.0$$
- **Decisive Win Rate**:
  $$\text{Decisive Win Rate} = \frac{\text{Won}}{\text{Won} + \text{Lost}}$$
- **Total Win Rate (Breakeven Integrity)**:
  $$\text{Total Win Rate} = \frac{\text{Won}}{\text{Won} + \text{Lost} + \text{Breakeven}}$$
- **Fixed Fractional Sizing**:
  $$\text{Position Size (Base Units)} = \frac{\text{Account Balance} \times 1\%}{|\text{Entry Price} - \text{Stop Loss}|}$$

