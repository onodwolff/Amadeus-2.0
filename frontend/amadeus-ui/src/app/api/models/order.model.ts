export type OrderSide = 'buy' | 'sell' | string;
export type OrderType = 'market' | 'limit' | 'stop' | 'stop_limit' | string;
export type OrderStatus = 'pending' | 'working' | 'filled' | 'cancelled' | 'rejected' | string;
export type TimeInForce = 'GTC' | 'IOC' | 'FOK' | 'GTD' | string;

export interface OrderSummary {
  order_id: string;
  client_order_id?: string;
  venue_order_id?: string;
  symbol: string;
  venue: string;
  side: OrderSide;
  type: OrderType;
  quantity: number;
  filled_quantity: number;
  price?: number;
  average_price?: number;
  status: OrderStatus;
  time_in_force?: TimeInForce;
  created_at: string;
  updated_at?: string;
}

export interface ExecutionReport {
  order_id: string;
  execution_id: string;
  symbol: string;
  venue: string;
  price: number;
  quantity: number;
  side: OrderSide;
  liquidity?: 'maker' | 'taker' | string;
  fees?: number;
  timestamp: string;
}

export interface OrdersResponse {
  orders: OrderSummary[];
  executions?: ExecutionReport[];
}

export interface OrderResponse {
  order: OrderSummary;
}
