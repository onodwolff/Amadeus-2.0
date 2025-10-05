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

export type OrderBookSideLevels = [number, number][];

export interface OrderBookSnapshot {
  type: 'snapshot';
  instrument_id: string;
  timestamp: string;
  bids: OrderBookSideLevels;
  asks: OrderBookSideLevels;
}

export interface OrderBookDelta {
  type: 'delta';
  instrument_id: string;
  timestamp: string;
  bids: OrderBookSideLevels;
  asks: OrderBookSideLevels;
}

export type OrderBookMessage = OrderBookSnapshot | OrderBookDelta;

export interface MarketTrade {
  instrument_id: string;
  price: number;
  volume: number;
  side: 'buy' | 'sell';
  timestamp: string;
}
