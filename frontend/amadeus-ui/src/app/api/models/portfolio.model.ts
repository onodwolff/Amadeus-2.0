export interface Balance {
  currency: string;
  total: number;
  available: number;
  locked?: number;
  account_id?: string;
  account_name?: string;
  node_id?: string;
  venue?: string;
}

export interface Position {
  position_id: string;
  symbol: string;
  venue: string;
  quantity: number;
  average_price?: number;
  mark_price?: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
  margin_used?: number;
  account_id?: string;
  account_name?: string;
  node_id?: string;
  updated_at?: string;
}

export interface CashMovement {
  movement_id: string;
  account_id: string;
  account_name?: string;
  node_id?: string;
  venue?: string;
  currency: string;
  amount: number;
  type: 'deposit' | 'withdrawal' | 'transfer' | 'trade_pnl' | 'adjustment';
  description?: string;
  timestamp: string;
}

export interface PortfolioSummary {
  balances: Balance[];
  positions: Position[];
  cash_movements?: CashMovement[];
  equity_value?: number;
  margin_value?: number;
  timestamp: string;
}

export interface PortfolioResponse {
  portfolio: PortfolioSummary;
}

export interface PortfolioBalancesStreamMessage {
  balances: Balance[];
  equity_value?: number;
  margin_value?: number;
  timestamp: string;
}

export interface PortfolioPositionsStreamMessage {
  positions: Position[];
  equity_value?: number;
  margin_value?: number;
  timestamp: string;
}

export interface PortfolioMovementsStreamMessage {
  cash_movements: CashMovement[];
  equity_value?: number;
  margin_value?: number;
  timestamp: string;
}

export interface PortfolioHistoryPoint {
  timestamp: string;
  equity: number;
  realized: number;
  unrealized: number;
  exposures: Record<string, number>;
}

export interface PortfolioHistoryResponse {
  history: PortfolioHistoryPoint[];
}
