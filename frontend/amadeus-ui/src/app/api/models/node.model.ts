export type NodeMode = 'backtest' | 'live' | string;
export type NodeStatus = 'created' | 'running' | 'stopped' | 'error' | string;

export interface NodeMetrics {
  pnl?: number;
  latency_ms?: number;
}

export interface NodeHandle {
  id: string;
  mode: NodeMode;
  status: NodeStatus;
  detail?: string;
  metrics?: NodeMetrics;
}

export interface NodesListResponse {
  nodes: NodeHandle[];
}

export interface NodeResponse {
  node: NodeHandle;
}

export interface NodesStreamMessage {
  nodes: NodeHandle[];
}
