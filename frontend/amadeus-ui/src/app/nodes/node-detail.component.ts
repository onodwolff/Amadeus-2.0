import { CommonModule } from '@angular/common';
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import {
  NodeConfiguration,
  NodeDetailResponse,
  NodeHandle,
  NodeLifecycleEvent,
  NodeLogEntry,
} from '../api/models';
import { WsConnectionState } from '../ws.service';
import { NodeMetricsPanelComponent } from './components/node-metrics/node-metrics-panel.component';

@Component({
  selector: 'app-node-detail',
  standalone: true,
  imports: [CommonModule, NodeMetricsPanelComponent],
  templateUrl: './node-detail.component.html',
  styleUrls: ['./node-detail.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodeDetailComponent implements AfterViewInit, OnChanges {
  @Input() node: NodeHandle | null = null;
  @Input() detail: NodeDetailResponse | null = null;
  @Input() lifecycle: NodeLifecycleEvent[] | null = null;
  @Input() logs: NodeLogEntry[] | null = null;
  @Input() isLoadingDetail = false;
  @Input() isLoadingLogs = false;
  @Input() detailError: string | null = null;
  @Input() logsError: string | null = null;
  @Input() logStreamState: WsConnectionState = 'connecting';
  @Input() isRestarting = false;
  @Input() isStopping = false;
  @Input() isDownloadingLogs = false;
  @Input() isDeleting = false;

  @Output() readonly closed = new EventEmitter<void>();
  @Output() readonly restartRequested = new EventEmitter<void>();
  @Output() readonly stopRequested = new EventEmitter<void>();
  @Output() readonly logsDownloadRequested = new EventEmitter<void>();
  @Output() readonly deleteRequested = new EventEmitter<void>();

  @ViewChild('pnlChart') private pnlChart?: ElementRef<HTMLCanvasElement>;

  private _pnlHistory: number[] = [];
  private lastNodeId: string | null = null;
  private viewReady = false;
  private renderPending = false;

  readonly trackLifecycle = (_: number, item: NodeLifecycleEvent) => `${item.timestamp}-${item.status}`;
  readonly trackLog = (_: number, item: NodeLogEntry) => item.id;

  get hasLifecycle(): boolean {
    return Array.isArray(this.lifecycle) && this.lifecycle.length > 0;
  }

  get hasLogs(): boolean {
    return Array.isArray(this.logs) && this.logs.length > 0;
  }

  get configuration(): NodeConfiguration | null {
    return this.detail?.config ?? null;
  }

  get pnlSampleCount(): number {
    return this._pnlHistory.length;
  }

  get latestPnl(): number | null {
    if (!this._pnlHistory.length) {
      return null;
    }
    return this._pnlHistory[this._pnlHistory.length - 1];
  }

  ngOnChanges(changes: SimpleChanges): void {
    if ('node' in changes) {
      const current = changes['node'].currentValue as NodeHandle | null;
      const currentId = current?.id ?? null;
      if (currentId !== this.lastNodeId) {
        this.lastNodeId = currentId;
        this._pnlHistory = [];
        this.scheduleRender();
      }
      this.ingestMetrics(current);
    }
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    this.scheduleRender(true);
  }

  @HostListener('window:resize')
  onWindowResize(): void {
    this.scheduleRender(true);
  }

  private ingestMetrics(node: NodeHandle | null): void {
    const metrics = node?.metrics;
    if (!metrics) {
      return;
    }
    const pnlCandidate = metrics['pnl'];
    const pnl = typeof pnlCandidate === 'number' ? pnlCandidate : Number(pnlCandidate);
    if (!Number.isFinite(pnl)) {
      return;
    }
    this._pnlHistory.push(pnl);
    if (this._pnlHistory.length > 180) {
      this._pnlHistory = this._pnlHistory.slice(-180);
    }
    this.scheduleRender();
  }

  private scheduleRender(force = false): void {
    if (!this.viewReady) {
      return;
    }
    if (this.renderPending && !force) {
      return;
    }
    this.renderPending = true;
    const raf =
      typeof window !== 'undefined' && window.requestAnimationFrame
        ? window.requestAnimationFrame.bind(window)
        : null;
    if (raf) {
      raf(() => {
        this.renderPending = false;
        this.renderChart();
      });
    } else {
      this.renderPending = false;
      this.renderChart();
    }
  }

  private renderChart(): void {
    const canvasRef = this.pnlChart;
    if (!canvasRef) {
      return;
    }
    const canvas = canvasRef.nativeElement;
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const width = rect.width || 320;
    const height = rect.height || 140;
    const dpr =
      typeof window !== 'undefined' && window.devicePixelRatio
        ? window.devicePixelRatio
        : 1;
    const displayWidth = Math.max(1, Math.floor(width * dpr));
    const displayHeight = Math.max(1, Math.floor(height * dpr));

    if (canvas.width !== displayWidth || canvas.height !== displayHeight) {
      canvas.width = displayWidth;
      canvas.height = displayHeight;
    }

    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);

    const values = this._pnlHistory;
    if (values.length === 0) {
      return;
    }

    context.fillStyle = 'rgba(15, 23, 42, 0.75)';
    context.fillRect(0, 0, width, height);

    if (values.length < 2) {
      return;
    }

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, 1e-6);
    const padding = { top: 12, bottom: 16, left: 8, right: 8 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;

    context.lineWidth = 2;
    context.strokeStyle = '#38bdf8';
    context.beginPath();
    values.forEach((value, index) => {
      const ratio = index / (values.length - 1);
      const x = padding.left + ratio * chartWidth;
      const y =
        padding.top + chartHeight - ((value - min) / range) * chartHeight;
      if (index === 0) {
        context.moveTo(x, y);
      } else {
        context.lineTo(x, y);
      }
    });
    context.stroke();

    if (min < 0 && max > 0) {
      const zeroRatio = (0 - min) / range;
      const zeroY = padding.top + chartHeight - zeroRatio * chartHeight;
      context.save();
      context.setLineDash([4, 4]);
      context.strokeStyle = 'rgba(148, 163, 184, 0.35)';
      context.beginPath();
      context.moveTo(padding.left, zeroY);
      context.lineTo(padding.left + chartWidth, zeroY);
      context.stroke();
      context.restore();
    }

    const latest = values[values.length - 1];
    const latestX = padding.left + chartWidth;
    const latestY =
      padding.top + chartHeight - ((latest - min) / range) * chartHeight;
    context.fillStyle = '#f8fafc';
    context.beginPath();
    context.arc(latestX, latestY, 3.5, 0, Math.PI * 2);
    context.fill();
  }
}
