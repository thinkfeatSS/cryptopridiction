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

export interface MacroEvent {
  name: string;
  category: "EMPLOYMENT_DATA" | "CPI_INFLATION" | "FOMC_DECISION" | "POWELL_SPEECH" | string;
  impact: "CRITICAL" | "HIGH" | "MEDIUM" | string;
  time_utc: string;
  description: string;
  minutes_until: number;
}

export interface MacroCalendar {
  has_macro_event: boolean;
  has_upcoming_event: boolean;
  event_name: string | null;
  category: string | null;
  impact: string | null;
  event_time_utc: string | null;
  minutes_until_event: number | null;
  is_volatility_pause_active: boolean;
  pause_reason: string | null;
  fed_blackout_active: boolean;
  upcoming_events: MacroEvent[];
}

export interface DominanceMatrix {
  btc_dominance_pct: number;
  eth_dominance_pct: number;
  usdt_dominance_pct: number;
  stablecoin_dominance_pct: number;
  others_dominance_pct: number;
  capital_rotation_regime: "ALT_SEASON_EXPANSION" | "BITCOIN_DOMINANCE" | "STABLECOIN_FLIGHT" | "BALANCED_ROTATION" | string;
  rotation_description: string;
  alt_sizing_multiplier: number;
  btc_sizing_multiplier: number;
  updated_at_utc: string;
}

export interface DualSentiment {
  crypto_fear_and_greed: {
    score: number;
    classification: string;
    trend_7d?: string;
    stance?: string;
    directive?: string;
    is_extreme_fear_accumulation: boolean;
    is_extreme_greed_distribution: boolean;
  };
  traditional_fear_and_greed: {
    score: number;
    classification: string;
    proxy_benchmark: string;
  };
  sentiment_divergence: {
    delta: number;
    status: string;
    description: string;
  };
  updated_at_utc: string;
}

export interface EtfFundFlow {
  daily_net_flow_usd_m: number;
  cumulative_5d_flow_usd_m: number;
  top_inflow_fund?: string;
  top_inflow_amount_usd_m?: number;
  top_outflow_fund?: string;
  top_outflow_amount_usd_m?: number;
  flow_direction: "NET_INFLOW" | "NET_OUTFLOW" | string;
}

export interface EtfFlows {
  bitcoin_spot_etf: EtfFundFlow;
  ethereum_spot_etf: EtfFundFlow;
  institutional_bias: string;
  institutional_description: string;
  veto_macro_btc_shorts: boolean;
  updated_at_utc: string;
}

export interface ExchangeFlows {
  btc_exchange_flow: {
    inflow_24h_usd_m: number;
    outflow_24h_usd_m: number;
    net_flow_24h_usd_m: number;
    is_supply_squeeze: boolean;
    is_deposit_dump_risk: boolean;
  };
  stablecoin_exchange_flow: {
    inflow_24h_usd_m: number;
    outflow_24h_usd_m: number;
    net_dry_powder_inflow_usd_m: number;
    has_buying_capacity_surge: boolean;
  };
  flow_regime: string;
  flow_description: string;
  updated_at_utc: string;
}

export interface WhaleWall {
  price: number;
  size: number;
  notional_usd: number;
}

export interface HyperliquidWhaleRadar {
  symbol: string;
  mark_price: number;
  funding_rate_8h_pct: number;
  open_interest_coins: number;
  open_interest_usd: number;
  whale_bid_walls: WhaleWall[];
  whale_ask_walls: WhaleWall[];
  total_whale_bid_notional_usd: number;
  total_whale_ask_notional_usd: number;
  whale_bias: "BULLISH_WHALE_BID_ABSORPTION" | "BEARISH_WHALE_ASK_RESISTANCE" | "BULLISH_AGGREGATE_BID_PRESSURE" | "BEARISH_AGGREGATE_ASK_PRESSURE" | "BALANCED_ORDER_FLOW" | string;
  confluence_boost_pct: number;
  data_source?: string;
  dynamic_threshold_usd?: number;
  order_flow_imbalance_pct?: number;
  total_visible_depth_usd?: number;
  updated_at_utc: string;
}

export interface LiquidationPool {
  leverage: string;
  price: number;
  distance_pct: number;
  density: string;
}

export interface LiquidationHeatmap {
  symbol: string;
  current_price: number;
  short_liquidation_pools: LiquidationPool[];
  long_liquidation_pools: LiquidationPool[];
  target_magnet_long: number;
  target_magnet_short: number;
  recommendation: string;
}

export interface MarketIntelligencePayload {
  macro_calendar: MacroCalendar;
  dominance_matrix: DominanceMatrix;
  dual_sentiment: DualSentiment;
  etf_flows: EtfFlows;
  exchange_flows: ExchangeFlows;
  hyperliquid_whale_radar: HyperliquidWhaleRadar;
  liquidation_heatmap: LiquidationHeatmap;
  synthesized_at_utc: string;
}

export interface MarketIntelligenceResponse {
  status: string;
  symbol: string;
  market_intelligence: MarketIntelligencePayload;
}

export interface V16EndpointHealth {
  endpoint: string;
  status: number | "ERR";
  latencyMs: number;
  lastUpdated: string;
  itemCount: number;
}
