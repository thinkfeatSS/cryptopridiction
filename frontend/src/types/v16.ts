/**
 * QUANT EDGE V16: Strict TypeScript Data Contracts
 * Directly mirrors the production backend payloads from:
 * - GET /api/v16/signals
 * - GET /api/v16/theses
 * - GET /api/v16/events
 * - GET /api/v16/regime
 */

export interface V16ImmutableSignal {
  signal_id: string;
  trade_thesis_id: string;
  model_version: string;
  strategy_version: string;
  symbol: string;
  direction: "LONG" | "SHORT" | string;
  horizon: string;
  signal_generated_at: string;
  entry_price_initial: number;
  tp1_initial: number;
  tp2_initial: number;
  tp3_initial: number;
  sl_initial: number;
  regime: string;
  p_tp1: number;
  p_tp2: number;
  p_tp3: number;
  p_sl: number;
  expected_gross_return: number;
  expected_net_return: number;
  total_execution_costs: number;
  risk_reward: number;
  signal_score: number;
  grade: string;
  status: string;
  liquidity_score?: number;
  data_quality_score?: number;
}

export interface V16DynamicTradeState {
  signal_id: string;
  current_price: number;
  current_sl: number;
  trailing_sl: number | null;
  locked_sl: number | null;
  unrealized_net_pnl_pct: number;
  mfe_pct: number;
  mae_pct: number;
  is_tp1_locked: boolean;
  is_tp2_locked: boolean;
  status: string;
  outcome_label: string;
  updated_at_utc: string;
}

export interface V16SignalEnvelope {
  immutable: V16ImmutableSignal;
  dynamic: V16DynamicTradeState;
}

export interface V16SignalsResponse {
  status: string;
  version: string;
  total: number;
  data: V16SignalEnvelope[];
}

export interface V16TradeThesis {
  thesis_id: string;
  symbol: string;
  direction: string;
  regime: string;
  participating_horizons: string[];
  signals: string[];
  highest_net_ev: number;
  created_at_utc: string;
  is_active?: boolean;
  active_signals_count?: number;
  current_price?: number;
  unrealized_net_pnl_pct?: number;
  mfe_pct?: number;
}

export interface V16ThesesResponse {
  status: string;
  total_theses: number;
  active_theses_count?: number;
  data: V16TradeThesis[];
}

export interface V16AuditEvent {
  event_id: string;
  signal_id: string;
  event_type: string;
  timestamp_utc: string;
  price_at_event: number;
  detail: string;
  metadata?: Record<string, any>;
}

export interface V16EventsResponse {
  status: string;
  count: number;
  data: V16AuditEvent[];
}

export interface V16RegimeResponse {
  status: string;
  regime: "BULL_TREND" | "BEAR_TREND" | "RANGE" | "HIGH_VOLATILITY" | "LOW_VOLATILITY" | "SQUEEZE" | "BREAKOUT" | "TRANSITION" | "UNKNOWN" | string;
  confidence: number;
  volatility_state: "LOW" | "MEDIUM" | "HIGH" | "EXTREME" | string;
  trend_strength: number;
  sizing_multiplier: number;
  eligible_strategies: string[];
  restricted_strategies?: string[];
  probabilities?: {
    bull: number;
    bear: number;
    range: number;
    breakout: number;
    squeeze: number;
  };
  metrics?: {
    btc_price?: number;
    adx?: number;
    rsi?: number;
    ema_fast?: number;
    ema_slow?: number;
    bb_width_percentile?: number;
    atr_percentile?: number;
    btc_shield_status?: string;
  };
  capital_preservation_reason?: string;
  updated_at_utc?: string;
  error?: string;
}

export interface V16EndpointHealth {
  endpoint: string;
  status: number | "ERR";
  latencyMs: number;
  lastUpdated: string;
  itemCount: number;
}
