export type NodeMode = 'backtest' | 'sandbox' | 'live' | string;
export type NodeStatus = 'created' | 'running' | 'stopped' | 'error' | string;

export type NodeMetricKey = 'pnl' | 'latency_ms' | 'cpu_percent' | 'memory_mb';

export interface NodeMetrics {
  pnl?: number;
  latency_ms?: number;
  cpu_percent?: number;
  memory_mb?: number;
}

export interface AdapterStatus {
  node_id?: string;
  name?: string;
  identifier?: string;
  mode?: string;
  state?: string;
  sandbox?: boolean;
  sources?: string[];
}

export interface NodeMetricPoint {
  timestamp: string;
  value: number;
}

export interface NodeMetricsSnapshot {
  timestamp: string;
  pnl: number;
  latency_ms: number;
  cpu_percent: number;
  memory_mb: number;
}

export interface NodeMetricsStreamMessage {
  series: Partial<Record<NodeMetricKey, NodeMetricPoint[]>>;
  latest?: NodeMetricsSnapshot | null;
}

export interface NodeHandle {
  id: string;
  mode: NodeMode;
  status: NodeStatus;
  detail?: string;
  metrics?: NodeMetrics;
  created_at?: string;
  updated_at?: string;
  adapters?: AdapterStatus[];
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
