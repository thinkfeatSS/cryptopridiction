export type NotificationType =
  | "NEW_SIGNAL"
  | "HYPE_SURGE"
  | "BLOWOFF_TOP"
  | "TP_HIT"
  | "SL_HIT"
  | "EXPIRED"
  | "BREAKEVEN_PROTECTED";

export interface SignalNotification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  symbol: string;
  horizon: string;
  direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH";
  entryPrice?: number;
  currentPrice?: number;
  targetPrice?: number;
  stopLossPrice?: number;
  realizedPnlPct?: number;
  conviction?: number;
  metaWinProb?: number;
  grade?: string;
  status?: string;
  timestamp: string;
  timestampMs: number;
  isRead: boolean;
  rawSignal?: any;
}
