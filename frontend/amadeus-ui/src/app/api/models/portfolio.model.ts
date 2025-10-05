export interface Balance {
  currency: string;
  total: number;
  available: number;
  locked?: number;
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
  updated_at?: string;
}

export interface PortfolioSummary {
  balances: Balance[];
  positions: Position[];
  equity_value?: number;
  timestamp: string;
}

export interface PortfolioResponse {
  portfolio: PortfolioSummary;
}
