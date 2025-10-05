import { map, Observable } from 'rxjs';
import { NodeHandle, NodeMetrics, NodesStreamMessage } from '../api/models';
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
