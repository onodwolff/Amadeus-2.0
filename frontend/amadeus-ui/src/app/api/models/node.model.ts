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

export interface NodeLaunchStrategyParameter {
  key: string;
  value: string;
}

export interface NodeLaunchStrategy {
  id: string;
  name: string;
  parameters: NodeLaunchStrategyParameter[];
}

export interface NodeLaunchDataSource {
  id: string;
  label: string;
  type: string;
  mode: string;
  enabled: boolean;
}

export interface NodeLaunchKeyReference {
  alias: string;
  keyId: string;
  required: boolean;
}

export interface NodeLaunchConstraints {
  maxRuntimeMinutes: number | null;
  maxDrawdownPercent: number | null;
  autoStopOnError: boolean;
  concurrencyLimit: number | null;
}

export interface NodeLaunchRequest {
  type: NodeMode;
  strategy: NodeLaunchStrategy;
  dataSources: NodeLaunchDataSource[];
  keyReferences: NodeLaunchKeyReference[];
  constraints: NodeLaunchConstraints;
}
