import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, signal } from '@angular/core';
import { NodesApi } from '../api/clients/nodes.api';
import { SystemApi } from '../api/clients/system.api';
import { CoreInfo, HealthStatus, NodeHandle, NodeLaunchRequest, NodeMode } from '../api/models';
import { WsService } from '../ws.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { observeNodesStream } from '../ws';
import { WsConnectionState } from '../ws.service';
import { NodeLaunchDialogComponent } from './node-launch-dialog.component';

@Component({
  standalone: true,
  selector: 'app-nodes-page',
  imports: [CommonModule, NodeLaunchDialogComponent],
  templateUrl: './nodes.page.html',
  styleUrls: ['./nodes.page.scss'],
})
export class NodesPage implements OnInit {
  readonly nodes = signal<NodeHandle[]>([]);
  readonly isLoading = signal(false);
  readonly isLaunching = signal(false);
  readonly wsState = signal<WsConnectionState>('connecting');
  readonly errorText = signal<string | null>(null);
  readonly coreInfo = signal<CoreInfo | null>(null);
  readonly healthInfo = signal<HealthStatus | null>(null);

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
        const detail = err?.error?.detail || 'Failed to launch node.';
        const message = typeof detail === 'string' ? detail : 'Failed to launch node.';
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
