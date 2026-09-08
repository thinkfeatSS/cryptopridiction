const API_BASE = typeof window !== "undefined" ? "" : (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000");

export interface SignalItem {
  id: number;
  signal_id: string;
  date_utc: string;
  time_utc: string;
  rank: string;
  quality_grade: string;
  grade_tier: number;
  symbol: string;
  horizon: string;
  direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH" | string;
  conviction_pct: number;
  entry_price: number;
  tp1_price: number;
  tp2_price: number;
  tp3_price: number;
  sl_price: number;
  risk_reward_ratio: string;
  expected_return_pct: number;
  decision: string;
  paper_trading_status: string;
  predicted_window: string;
  status: string;
  outcome_label: string;
  peak_price_seen: number;
  trough_price_seen: number;
  max_potential_gain_pct: number;
  exit_price?: number;
  realized_return_pct?: string;
  realized_return_num?: number;
  evaluated_at_utc?: string;
  card?: string;
}

export interface KpiSummary {
  last_updated_utc: string;
  total_trader_signals: number;
  won_signals_count: number;
  lost_signals_count: number;
  pending_signals_count: number;
  expired_signals_count: number;
  win_rate_pct: number;
  grade_a_plus_win_rate_pct: number;
  grade_a_win_rate_pct: number;
  average_return_pct: number;
  cumulative_return_pct: number;
}

export interface DailySummaryItem {
  date: string;
  total_signals: number;
  won_count: number;
  lost_count: number;
  pending_count: number;
  expired_count: number;
  win_rate_pct: number;
  cumulative_return_pct: number;
  average_return_pct: number;
}

export interface BtcMarketShield {
  active: boolean;
  status_code?: "NORMAL" | "BULL_MOMENTUM" | "CAUTION" | "DEFENSIVE" | "ALERT_DUMP" | string;
  reason: string;
  btc_15m_change_pct?: number;
  btc_1h_change_pct?: number;
  altcoin_longs_allowed?: boolean;
}

export interface EngineStatus {
  status: string;
  is_engine_active: boolean;
  is_scanning?: boolean;
  scan_status?: string;
  current_time_utc: string;
  next_scan_utc: string;
  seconds_to_next_scan: number;
  scan_version?: number;
  full_scan_version?: number;
  portfolio_version?: number;
  last_scan_timestamp?: string;
  btc_market_shield?: BtcMarketShield;
}

export interface OpenPosition {
  id: number;
  trade_id: string;
  symbol: string;
  horizon: string;
  direction: "BULLISH" | "BEARISH" | "LONG" | "SHORT" | string;
  allocated_usd: number;
  entry_price: number;
  current_price: number;
  tp_price: number;
  sl_price: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pct: number;
  target_progress_pct: number;
  unrealized_fee_usd: number;
  opened_at: string;
  expiry_time: string;
}

export interface ClosedTradeItem {
  id: number;
  trade_id: string;
  symbol: string;
  horizon: string;
  direction: "BULLISH" | "BEARISH" | "LONG" | "SHORT" | string;
  entry_price: number;
  exit_price: number;
  exit_reason: string;
  outcome: "WON" | "LOST" | "BREAKEVEN" | string;
  gross_pnl_usd: number;
  binance_fee_usd: number;
  realized_pnl_usd: number;
  realized_pnl_pct: number;
  duration_str: string;
  opened_at: string;
  closed_at: string;
}

export interface QueuedTrade {
  trade_id: string;
  symbol: string;
  horizon: string;
  direction: string;
  entry_price: number;
  tp_price: number;
  tp1_price: number;
  tp2_price?: number;
  tp3_price?: number;
  sl_price: number;
  position_size_usd: number;
  est_net_profit_usd: number;
  est_net_gain_pct: number;
  past_won: number;
  past_lost: number;
  win_ratio_label: string;
  signal_decision: string;
  status: string;
  status_reason: string;
  queued_at: string;
  predicted_window?: string;
}

export interface PortfolioData {
  initial_capital_usd: number;
  current_balance_usd: number;
  open_positions: OpenPosition[];
  closed_trades_history: ClosedTradeItem[];
  queued_trades?: QueuedTrade[];
  total_trades_count: number;
  winning_trades_count: number;
  losing_trades_count: number;
  breakeven_trades_count?: number;
  win_rate_pct: number;
  total_net_profit_usd: number;
  fee_tier_label?: string;
}

export interface ForecastData {
  timestamp: string;
  strategy: string;
  btc_market_shield?: BtcMarketShield;
  top_round_signals: any[];
  scanner_leaderboard: any[];
  deep_dive: any;
}

export async function fetchKpi(): Promise<KpiSummary> {
  const res = await fetch(`${API_BASE}/api/signals/kpi`);
  if (!res.ok) throw new Error("Failed fetching KPI metrics");
  return res.json();
}

export async function fetchDailySummary(): Promise<DailySummaryItem[]> {
  const res = await fetch(`${API_BASE}/api/signals/daily-summary`);
  if (!res.ok) throw new Error("Failed fetching daily summary");
  return res.json();
}

export async function fetchSignals(params?: {
  search?: string;
  date?: string;
  outcome?: string;
  grade?: string;
  horizon?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; signals: SignalItem[] }> {
  const query = new URLSearchParams();
  if (params?.search) query.append("search", params.search);
  if (params?.date) query.append("date", params.date);
  if (params?.outcome) query.append("outcome", params.outcome);
  if (params?.grade) query.append("grade", params.grade);
  if (params?.horizon) query.append("horizon", params.horizon);
  if (params?.limit) query.append("limit", params.limit.toString());
  if (params?.offset) query.append("offset", params.offset.toString());

  const res = await fetch(`${API_BASE}/api/signals?${query.toString()}`);
  if (!res.ok) throw new Error("Failed fetching signals");
  return res.json();
}

export async function fetchSignalsBySymbol(symbol: string): Promise<SignalItem[]> {
  const encoded = encodeURIComponent(symbol);
  const res = await fetch(`${API_BASE}/api/signals/by-symbol/${encoded}`);
  if (!res.ok) {
    // Fallback to standard signals query
    const res2 = await fetch(`${API_BASE}/api/signals?symbol=${encoded}&limit=100`);
    if (!res2.ok) return [];
    const data = await res2.json();
    return data.signals || [];
  }
  return res.json();
}

export async function fetchPortfolio(): Promise<PortfolioData> {
  const res = await fetch(`${API_BASE}/api/portfolio`);
  if (!res.ok) throw new Error("Failed fetching portfolio");
  return res.json();
}

export async function fetchForecast(): Promise<ForecastData> {
  const res = await fetch(`${API_BASE}/api/forecast`);
  if (!res.ok) throw new Error("Failed fetching forecast");
  return res.json();
}

export async function fetchStatus(): Promise<EngineStatus> {
  const res = await fetch(`${API_BASE}/api/status`);
  if (!res.ok) throw new Error("Failed fetching status");
  return res.json();
}
