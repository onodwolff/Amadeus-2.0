import { map, Observable } from 'rxjs';
import {
  NodeEventsStreamMessage,
  NodeHandle,
  NodeMetricKey,
  NodeMetricPoint,
  NodeMetrics,
  NodeMetricsSnapshot,
  NodeMetricsStreamMessage,
  NodesStreamMessage,
} from '../api/models';
import { WsService, WsConnectionState } from '../ws.service';

export interface NodesStreamObservables {
  readonly nodes$: Observable<NodeHandle[]>;
  readonly state$: Observable<WsConnectionState>;
}

export interface NodeMetricsSummary {
  readonly id: string;
  readonly metrics: NodeMetrics | null;
}

export interface NodesMetricsObservables {
  readonly metrics$: Observable<NodeMetricsSummary[]>;
  readonly state$: Observable<WsConnectionState>;
}

export interface NodeEventsStreamObservables {
  readonly events$: Observable<NodeEventsStreamMessage>;
  readonly state$: Observable<WsConnectionState>;
}

export interface NodeMetricSeriesPayload {
  readonly series: Record<NodeMetricKey, NodeMetricPoint[]>;
  readonly latest: NodeMetricsSnapshot | null;
}

export interface NodeMetricSeriesObservables {
  readonly metrics$: Observable<NodeMetricSeriesPayload>;
  readonly state$: Observable<WsConnectionState>;
}

export function observeNodesStream(ws: WsService): NodesStreamObservables {
  const channel = ws.channel<NodesStreamMessage>({
    name: 'nodes-stream',
    path: '/ws/nodes',
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  const nodes$ = channel.messages$.pipe(
    map((message) => (Array.isArray(message?.nodes) ? message.nodes : [])),
  );

  return {
    nodes$,
    state$: channel.state$,
  };
}

export function observeNodesMetrics(ws: WsService): NodesMetricsObservables {
  const { nodes$, state$ } = observeNodesStream(ws);
  const metrics$ = nodes$.pipe(
    map((nodes) =>
      nodes.map((node) => ({
        id: node.id,
        metrics: node.metrics ?? null,
      })),
    ),
  );

  return {
    metrics$,
    state$,
  };
}

export function observeNodeEventsStream(
  nodeId: string,
  ws: WsService,
): NodeEventsStreamObservables {
  const channel = ws.channel<NodeEventsStreamMessage>({
    name: `node-events-${nodeId}`,
    path: `/ws/nodes/${encodeURIComponent(nodeId)}/logs`,
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  return {
    events$: channel.messages$,
    state$: channel.state$,
  };
}

export function observeNodeMetricsStream(
  nodeId: string,
  ws: WsService,
): NodeMetricSeriesObservables {
  const channel = ws.channel<NodeMetricsStreamMessage>({
    name: `node-metrics-${nodeId}`,
    path: `/ws/nodes/${encodeURIComponent(nodeId)}/metrics`,
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  const metrics$ = channel.messages$.pipe(
    map((message): NodeMetricSeriesPayload => {
      const series = message?.series ?? {};
      const coerce = (key: NodeMetricKey): NodeMetricPoint[] => {
        const points = series[key];
        if (!Array.isArray(points)) {
          return [];
        }
        return points
          .filter((point): point is NodeMetricPoint =>
            typeof point === 'object' && point !== null && typeof point.timestamp === 'string' &&
            typeof point.value === 'number',
          )
          .sort((a, b) => (a.timestamp < b.timestamp ? -1 : a.timestamp > b.timestamp ? 1 : 0));
      };

      return {
        series: {
          pnl: coerce('pnl'),
          latency_ms: coerce('latency_ms'),
          cpu_percent: coerce('cpu_percent'),
          memory_mb: coerce('memory_mb'),
        },
        latest: message?.latest ?? null,
      };
    }),
  );

  return {
    metrics$,
    state$: channel.state$,
  };
}
