import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { ApiService } from '../api.service';
import { WsService } from '../ws.service';

export interface NodeMetrics {
  pnl?: number;
  latency_ms?: number;
}

export interface NodeHandle {
  id: string;
  mode: 'backtest' | 'live' | string;
  status: string;
  detail?: string;
  metrics?: NodeMetrics;
}

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
  readonly coreInfo = signal<any>(null);
  readonly healthInfo = signal<any>(null);

  private unsubscribeWs?: () => void;
  private refreshTimer?: any;

  constructor(private readonly api: ApiService, private readonly ws: WsService) {}

  ngOnInit(): void {
    this.api.health().subscribe({ next: (h) => this.healthInfo.set(h), error: (err) => console.error(err) });
    this.api.coreInfo().subscribe({ next: (c) => this.coreInfo.set(c), error: (err) => console.error(err) });
    this.fetchNodes();

    this.unsubscribeWs = this.ws.subscribe(
      '/ws/nodes',
      (payload) => {
        if (payload?.nodes) {
          this.nodes.set(payload.nodes);
        }
      },
      {
        onOpen: () => this.wsState.set('connected'),
        onClose: () => this.wsState.set('disconnected'),
        onError: (err) => {
          console.error(err);
          this.wsState.set('disconnected');
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
    this.api.startBacktest().subscribe({
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
    this.api.startLive().subscribe({
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
    this.api.stopNode(node.id).subscribe({
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
    this.api.nodes().subscribe({
      next: (response: any) => {
        const list = Array.isArray(response) ? response : response?.nodes;
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
