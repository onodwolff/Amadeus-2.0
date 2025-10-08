export type OrderSide = 'buy' | 'sell' | string;
export type OrderType = 'market' | 'limit' | 'stop' | 'stop_limit' | string;
export type OrderStatus = 'pending' | 'working' | 'filled' | 'cancelled' | 'rejected' | string;
export type TimeInForce = 'GTC' | 'IOC' | 'FOK' | 'GTD' | string;

export interface OrderSummary {
  order_id: string;
  client_order_id?: string | null;
  venue_order_id?: string | null;
  symbol: string;
  venue: string;
  side: OrderSide;
  type: OrderType;
  quantity: number;
  filled_quantity: number;
  price?: number | null;
  average_price?: number | null;
  status: OrderStatus;
  time_in_force?: TimeInForce | null;
  expire_time?: string | null;
  post_only?: boolean | null;
  reduce_only?: boolean | null;
  limit_offset?: number | null;
  contingency_type?: 'OCO' | 'OTO' | string | null;
  order_list_id?: string | null;
  linked_order_ids?: string[] | null;
  parent_order_id?: string | null;
  node_id?: string | null;
  created_at: string;
  updated_at?: string | null;
  instructions?: Record<string, unknown> | null;
}

export interface ExecutionReport {
  order_id: string;
  execution_id: string;
  symbol: string;
  venue: string;
  price: number;
  quantity: number;
  side: OrderSide;
  liquidity?: 'maker' | 'taker' | string | null;
  fees?: number | null;
  timestamp: string;
  node_id?: string | null;
}

export interface OrdersResponse {
  orders: OrderSummary[];
  executions?: ExecutionReport[];
}

export interface OrderResponse {
  order: OrderSummary;
}

export interface CreateOrderPayload {
  symbol: string;
  venue: string;
  side: OrderSide;
  type: OrderType;
  quantity: number;
  price?: number;
  time_in_force?: TimeInForce | string;
  expire_time?: string;
  post_only?: boolean;
  reduce_only?: boolean;
  limit_offset?: number;
  contingency_type?: 'OCO' | 'OTO' | string;
  order_list_id?: string;
  linked_order_ids?: string[];
  parent_order_id?: string;
  node_id?: string;
  client_order_id?: string;
}

export interface ModifyOrderPayload {
  quantity?: number;
  price?: number | null;
  time_in_force?: TimeInForce | string | null;
  expire_time?: string | null;
  post_only?: boolean | null;
  reduce_only?: boolean | null;
  limit_offset?: number | null;
  contingency_type?: 'OCO' | 'OTO' | string | null;
  order_list_id?: string | null;
  linked_order_ids?: string[];
  parent_order_id?: string | null;
  node_id?: string | null;
  client_order_id?: string | null;
}

export interface OrdersStreamMessage {
  orders?: OrderSummary[];
  executions?: ExecutionReport[];
}
