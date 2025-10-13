import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { NodesApi } from '../api/clients/nodes.api';
import { SystemApi } from '../api/clients/system.api';
import {
  CoreInfo,
  HealthStatus,
  NodeDetailResponse,
  NodeHandle,
  NodeMetrics,
  NodeLaunchRequest,
  NodeLifecycleEvent,
  NodeLogEntry,
  NodeMode,
} from '../api/models';
import { WsService } from '../ws.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { observeNodeEventsStream, observeNodesStream } from '../ws';
import { WsConnectionState } from '../ws.service';
import { NodeLaunchDialogComponent } from './node-launch-dialog.component';
import { NodeDetailComponent } from './node-detail.component';
import { Subscription } from 'rxjs';
import { EquitySparklineComponent } from './components/equity-sparkline/equity-sparkline.component';
import { AuthStateService } from '../shared/auth/auth-state.service';

@Component({
  standalone: true,
  selector: 'app-nodes-page',
  imports: [CommonModule, NodeLaunchDialogComponent, NodeDetailComponent, EquitySparklineComponent],
  templateUrl: './nodes.page.html',
  styleUrls: ['./nodes.page.scss'],
})
export class NodesPage implements OnInit, OnDestroy {
  readonly nodes = signal<NodeHandle[]>([]);
  readonly isLoading = signal(false);
  readonly isLaunching = signal(false);
  readonly wsState = signal<WsConnectionState>('connecting');
  readonly errorText = signal<string | null>(null);
  readonly coreInfo = signal<CoreInfo | null>(null);
  readonly healthInfo = signal<HealthStatus | null>(null);
  readonly selectedNodeId = signal<string | null>(null);
  readonly nodeDetail = signal<NodeDetailResponse | null>(null);
  readonly nodeLifecycle = signal<NodeLifecycleEvent[]>([]);
  readonly nodeLogs = signal<NodeLogEntry[]>([]);
  readonly isDetailLoading = signal(false);
  readonly isLogsLoading = signal(false);
  readonly detailError = signal<string | null>(null);
  readonly logsError = signal<string | null>(null);
  readonly logStreamState = signal<WsConnectionState>('connecting');
  readonly isDownloadingLogs = signal(false);
  readonly stoppingNodeId = signal<string | null>(null);
  readonly restartingNodeId = signal<string | null>(null);
  readonly deletingNodeId = signal<string | null>(null);
  readonly launchMode = signal<NodeMode>('backtest');

  private readonly nodesApi = inject(NodesApi);
  private readonly systemApi = inject(SystemApi);
  private readonly ws = inject(WsService);
  protected readonly authState = inject(AuthStateService);

  private logStreamSubscription: Subscription | null = null;
  private logStreamStateSubscription: Subscription | null = null;

  ngOnInit(): void {
    this.systemApi
      .health()
      .subscribe({ next: (h) => this.healthInfo.set(h), error: (err) => console.error(err) });
    this.systemApi
      .coreInfo()
      .subscribe({ next: (c) => this.coreInfo.set(c), error: (err) => console.error(err) });
    this.fetchNodes();

    const { nodes$, state$ } = observeNodesStream(this.ws);

    state$.pipe(takeUntilDestroyed()).subscribe((state) => this.wsState.set(state));

    nodes$.pipe(takeUntilDestroyed()).subscribe({
      next: (payload) => {
        this.nodes.set(payload);
      },
      error: (err) => {
        console.error(err);
        this.wsState.set('disconnected');
      },
    });
  }

  readonly hasNodes = computed(() => this.nodes().length > 0);
  readonly selectedNode = computed(() => {
    const id = this.selectedNodeId();
    if (!id) {
      return null;
    }
    return this.nodes().find((node) => node.id === id) ?? null;
  });
  readonly isStopping = computed(() => this.stoppingNodeId() !== null);
  readonly isRestarting = computed(() => this.restartingNodeId() !== null);
  readonly isDeleting = computed(() => this.deletingNodeId() !== null);
  readonly totalBots = computed(() => this.nodes().length);
  readonly runningBots = computed(
    () => this.nodes().filter((node) => node.status === 'running').length,
  );
  readonly pausedBots = computed(
    () => this.nodes().filter((node) => node.status !== 'running').length,
  );
  readonly totalPnl = computed(() =>
    this.nodes().reduce((sum, node) => sum + (this.resolveMetric(node, 'pnl') ?? 0), 0),
  );
  readonly totalEquity = computed(() =>
    this.nodes().reduce((sum, node) => sum + (this.resolveMetric(node, 'equity') ?? 0), 0),
  );
  readonly averageLatencyMs = computed(() => {
    const samples = this.nodes()
      .map((node) => this.resolveMetric(node, 'latency_ms'))
      .filter((value): value is number => value !== null);
    if (!samples.length) {
      return null;
    }
    const total = samples.reduce((acc, value) => acc + value, 0);
    return total / samples.length;
  });

  metric(node: NodeHandle, key: keyof NodeMetrics): number | null {
    return this.resolveMetric(node, key);
  }

  setLaunchMode(mode: NodeMode): void {
    this.launchMode.set(mode);
  }

  onLaunchModeChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    if (!target) {
      return;
    }
    this.setLaunchMode(target.value as NodeMode);
  }

  openWizard(dialog: NodeLaunchDialogComponent, nodeType: NodeMode): void {
    dialog.open(nodeType);
  }

  onLaunchNode(payload: NodeLaunchRequest, dialog: NodeLaunchDialogComponent): void {
    this.errorText.set(null);
    dialog.clearSubmissionError();
    this.isLaunching.set(true);
    this.nodesApi.launchNode(payload).subscribe({
      next: () => {
        dialog.markAsCompleted();
        this.fetchNodes();
      },
      error: (err) => {
        console.error(err);
        const detail = err?.error?.detail || 'Failed to launch bot.';
        const message = typeof detail === 'string' ? detail : 'Failed to launch bot.';
        this.errorText.set(message);
        dialog.setSubmissionError(message);
        this.isLaunching.set(false);
      },
      complete: () => {
        this.isLaunching.set(false);
      },
    });
  }

  stop(node: NodeHandle): void {
    if (this.stoppingNodeId() === node.id) {
      return;
    }
    this.errorText.set(null);
    this.stoppingNodeId.set(node.id);
    this.nodesApi.stopNode(node.id).subscribe({
      error: (err) => {
        console.error(err);
        this.errorText.set('Failed to stop bot.');
        this.stoppingNodeId.set(null);
      },
      next: () => {
        this.fetchNodes();
        if (this.selectedNodeId() === node.id) {
          this.loadNodeDetail(node.id);
        }
      },
      complete: () => {
        this.stoppingNodeId.set(null);
      },
    });
  }

  refresh(): void {
    this.fetchNodes();
  }

  openNodeDetail(node: NodeHandle): void {
    this.selectedNodeId.set(node.id);
    this.nodeDetail.set(null);
    this.nodeLifecycle.set([]);
    this.nodeLogs.set([]);
    this.detailError.set(null);
    this.logsError.set(null);
    this.isDetailLoading.set(true);
    this.isLogsLoading.set(true);
    this.logStreamState.set('connecting');
    this.loadNodeDetail(node.id);
    this.loadNodeLogs(node.id);
    this.connectNodeStream(node.id);
  }

  closeDetail(): void {
    this.selectedNodeId.set(null);
    this.nodeDetail.set(null);
    this.nodeLifecycle.set([]);
    this.nodeLogs.set([]);
    this.detailError.set(null);
    this.logsError.set(null);
    this.disposeNodeStream();
  }

  restart(node: NodeHandle): void {
    if (this.restartingNodeId() === node.id) {
      return;
    }
    this.errorText.set(null);
    this.restartingNodeId.set(node.id);
    this.nodesApi.restartNode(node.id).subscribe({
      next: () => {
        this.fetchNodes();
        if (this.selectedNodeId() === node.id) {
          this.loadNodeDetail(node.id);
        }
      },
      error: (err) => {
        console.error(err);
        this.errorText.set('Failed to restart bot.');
        this.restartingNodeId.set(null);
      },
      complete: () => {
        this.restartingNodeId.set(null);
      },
    });
  }

  delete(node: NodeHandle): void {
    if (this.deletingNodeId() === node.id) {
      return;
    }

    const confirmationMessage =
      `Delete trading bot ${node.id}? This will permanently remove its metrics, logs, and configuration history.`;
    const isConfirmed =
      typeof window === 'undefined' ? true : window.confirm(confirmationMessage);
    if (!isConfirmed) {
      return;
    }

    this.errorText.set(null);
    this.deletingNodeId.set(node.id);
    this.nodesApi.deleteNode(node.id).subscribe({
      next: () => {
        if (this.selectedNodeId() === node.id) {
          this.closeDetail();
        }
        this.fetchNodes();
      },
      error: (err) => {
        console.error(err);
        this.errorText.set('Failed to delete bot.');
        this.deletingNodeId.set(null);
      },
      complete: () => {
        this.deletingNodeId.set(null);
      },
    });
  }

  downloadLogs(node: NodeHandle): void {
    this.logsError.set(null);
    this.isDownloadingLogs.set(true);
    this.nodesApi.downloadNodeLogs(node.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${node.id}.log`;
        link.click();
        URL.revokeObjectURL(url);
      },
      error: (err) => {
        console.error(err);
        this.logsError.set('Failed to download logs.');
        this.isDownloadingLogs.set(false);
      },
      complete: () => {
        this.isDownloadingLogs.set(false);
      },
    });
  }

  onStopClick(event: MouseEvent, node: NodeHandle): void {
    event.stopPropagation();
    this.stop(node);
  }

  onStartClick(event: MouseEvent, node: NodeHandle): void {
    event.stopPropagation();
    this.restart(node);
  }

  onRestartClick(event: MouseEvent, node: NodeHandle): void {
    event.stopPropagation();
    this.restart(node);
  }

  onDeleteClick(event: MouseEvent, node: NodeHandle): void {
    event.stopPropagation();
    this.delete(node);
  }

  ngOnDestroy(): void {
    this.disposeNodeStream();
  }

  private resolveMetric(node: NodeHandle, key: keyof NodeMetrics): number | null {
    const summaryRecord = node.summary as Record<string, unknown> | undefined;
    const nodeRecord = node as unknown as Record<string, unknown>;
    const sources: unknown[] = [
      node.metrics?.[key],
      node.summary?.metrics?.[key],
      summaryRecord?.[key as string],
      nodeRecord[key as string],
    ];

    for (const candidate of sources) {
      const value = this.parseNumber(candidate);
      if (value !== null) {
        return value;
      }
    }
    return null;
  }

  private parseNumber(value: unknown): number | null {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : null;
    }
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (!trimmed) {
        return null;
      }
      const numeric = Number(trimmed);
      return Number.isFinite(numeric) ? numeric : null;
    }
    return null;
  }

  private fetchNodes(): void {
    this.isLoading.set(true);
    this.nodesApi.listNodes().subscribe({
      next: (response) => {
        const list = Array.isArray(response?.nodes) ? response.nodes : [];
        if (Array.isArray(list)) {
          this.nodes.set(list);
        }
        const selectedId = this.selectedNodeId();
        if (selectedId && !list.some((node) => node.id === selectedId)) {
          this.closeDetail();
        }
        this.isLoading.set(false);
      },
      error: (err) => {
        console.error(err);
        this.wsState.set('disconnected');
        this.errorText.set('Unable to load bots list.');
        this.isLoading.set(false);
      },
    });
  }

  private loadNodeDetail(nodeId: string): void {
    this.isDetailLoading.set(true);
    this.nodesApi.getNodeDetail(nodeId).subscribe({
      next: (detail) => {
        this.nodeDetail.set(detail);
        const lifecycle = Array.isArray(detail?.lifecycle) ? detail.lifecycle : [];
        this.nodeLifecycle.set(lifecycle);
        this.detailError.set(null);
      },
      error: (err) => {
        console.error(err);
        this.detailError.set('Unable to load node detail.');
        this.isDetailLoading.set(false);
      },
      complete: () => {
        this.isDetailLoading.set(false);
      },
    });
  }

  private loadNodeLogs(nodeId: string): void {
    this.isLogsLoading.set(true);
    this.nodesApi.getNodeLogs(nodeId).subscribe({
      next: (payload) => {
        const logs = Array.isArray(payload?.logs) ? payload.logs : [];
        this.nodeLogs.set(logs);
        this.logsError.set(null);
      },
      error: (err) => {
        console.error(err);
        this.logsError.set('Unable to load node logs.');
        this.isLogsLoading.set(false);
      },
      complete: () => {
        this.isLogsLoading.set(false);
      },
    });
  }

  private connectNodeStream(nodeId: string): void {
    this.disposeNodeStream();
    const { events$, state$ } = observeNodeEventsStream(nodeId, this.ws);
    this.logStreamState.set('connecting');
    this.logStreamStateSubscription = state$.subscribe((state) => this.logStreamState.set(state));
    this.logStreamSubscription = events$.subscribe({
      next: (payload) => {
        if (payload && Array.isArray(payload.logs)) {
          this.nodeLogs.set(payload.logs);
        }
        if (payload && Array.isArray(payload.lifecycle)) {
          this.nodeLifecycle.set(payload.lifecycle);
        }
      },
      error: (err) => {
        console.error(err);
        this.logStreamState.set('disconnected');
      },
    });
  }

  private disposeNodeStream(): void {
    this.logStreamSubscription?.unsubscribe();
    this.logStreamStateSubscription?.unsubscribe();
    this.logStreamSubscription = null;
    this.logStreamStateSubscription = null;
    this.logStreamState.set('disconnected');
  }
}
