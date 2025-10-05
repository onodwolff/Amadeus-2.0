export interface MarketBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface HistoricalBarsResponse {
  instrument_id: string;
  granularity: string;
  bars: MarketBar[];
}

export interface MarketTick {
  instrument_id: string;
  price: number;
  volume?: number;
  timestamp: string;
}
