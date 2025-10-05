import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { NodesApi } from '../api/clients/nodes.api';
import { SystemApi } from '../api/clients/system.api';
import { CoreInfo, HealthStatus, NodeHandle, NodesStreamMessage } from '../api/models';
import { WsService } from '../ws.service';

@Component({
  standalone: true,
  selector: 'app-nodes-page',
  imports: [CommonModule],
  templateUrl: './nodes.page.html',
  styleUrls: ['./nodes.page.scss'],
})
export class NodesPage implements OnInit, OnDestroy {
  readonly nodes = signal<NodeHandle[]>([]);
  readonly isLoading = signal(false);
  readonly wsState = signal<'connecting' | 'connected' | 'disconnected'>('connecting');
  readonly errorText = signal<string | null>(null);
  readonly coreInfo = signal<CoreInfo | null>(null);
  readonly healthInfo = signal<HealthStatus | null>(null);

  private unsubscribeWs?: () => void;
  private refreshTimer?: ReturnType<typeof setInterval>;

  constructor(
    private readonly nodesApi: NodesApi,
    private readonly systemApi: SystemApi,
    private readonly ws: WsService,
  ) {}

  ngOnInit(): void {
    this.systemApi
      .health()
      .subscribe({ next: (h) => this.healthInfo.set(h), error: (err) => console.error(err) });
    this.systemApi
      .coreInfo()
      .subscribe({ next: (c) => this.coreInfo.set(c), error: (err) => console.error(err) });
    this.fetchNodes();

    this.unsubscribeWs = this.ws.subscribe<NodesStreamMessage>(
      '/ws/nodes',
      (payload) => {
        if (payload?.nodes) {
          this.nodes.set(payload.nodes);
        }
      },
      {
        retryAttempts: Infinity,
        retryDelay: 1000,
        onOpen: () => this.wsState.set('connected'),
        onClose: () => this.wsState.set('disconnected'),
        onError: (err) => {
          console.error(err);
          this.wsState.set('connecting');
        },
      },
    );

    // fallback polling every 5 seconds
    this.refreshTimer = setInterval(() => this.fetchNodes(), 5000);
  }

  ngOnDestroy(): void {
    if (this.unsubscribeWs) {
      this.unsubscribeWs();
    }
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
    }
  }

  readonly hasNodes = computed(() => this.nodes().length > 0);

  startBacktest(): void {
    this.errorText.set(null);
    this.nodesApi.startBacktest().subscribe({
      error: (err) => {
        console.error(err);
        const detail = err?.error?.detail || 'Failed to start backtest node.';
        this.errorText.set(typeof detail === 'string' ? detail : 'Failed to start backtest node.');
      },
      next: () => this.fetchNodes(),
    });
  }

  startLive(): void {
    this.errorText.set(null);
    this.nodesApi.startLive().subscribe({
      error: (err) => {
        console.error(err);
        const detail = err?.error?.detail || 'Failed to start live node.';
        this.errorText.set(typeof detail === 'string' ? detail : 'Failed to start live node.');
      },
      next: () => this.fetchNodes(),
    });
  }

  stop(node: NodeHandle): void {
    this.errorText.set(null);
    this.nodesApi.stopNode(node.id).subscribe({
      error: (err) => {
        console.error(err);
        this.errorText.set('Failed to stop node.');
      },
      next: () => this.fetchNodes(),
    });
  }

  refresh(): void {
    this.fetchNodes();
  }

  private fetchNodes(): void {
    this.isLoading.set(true);
    this.nodesApi.listNodes().subscribe({
      next: (response) => {
        const list = Array.isArray(response?.nodes) ? response.nodes : [];
        if (Array.isArray(list)) {
          this.nodes.set(list);
        }
        this.isLoading.set(false);
      },
      error: (err) => {
        console.error(err);
        this.wsState.set('disconnected');
        this.errorText.set('Unable to load nodes list.');
        this.isLoading.set(false);
      },
    });
  }
}
