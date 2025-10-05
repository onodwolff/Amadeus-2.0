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
  created_at?: string;
  updated_at?: string;
}

export interface NodesListResponse {
  nodes: NodeHandle[];
}

export interface NodeResponse {
  node: NodeHandle;
}

export interface NodeLifecycleEvent {
  timestamp: string;
  status: string;
  message: string;
}

export interface NodeLogEntry {
  id: string;
  timestamp: string;
  level: string;
  message: string;
  source: string;
}

export interface NodeConfiguration {
  type?: NodeMode;
  strategy?: {
    id?: string;
    name?: string;
    parameters?: NodeLaunchStrategyParameter[];
  };
  dataSources?: NodeLaunchDataSource[];
  keyReferences?: NodeLaunchKeyReference[];
  constraints?: Partial<NodeLaunchConstraints>;
  [key: string]: unknown;
}

export interface NodeDetailResponse {
  node: NodeHandle;
  config: NodeConfiguration;
  lifecycle: NodeLifecycleEvent[];
}

export interface NodeLogsResponse {
  logs: NodeLogEntry[];
}

export interface NodesStreamMessage {
  nodes: NodeHandle[];
}

export interface NodeEventsStreamMessage {
  logs: NodeLogEntry[];
  lifecycle: NodeLifecycleEvent[];
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
