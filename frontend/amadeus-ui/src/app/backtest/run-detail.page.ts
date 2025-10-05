import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { BacktestsApi } from '../api/clients';
import {
  BacktestMetricPointDto,
  BacktestRunDetailDto,
  BacktestRunMetricsDto,
  BacktestRunProgressMessage,
  BacktestRunSummaryMetricDto,
  BacktestTradeStatDto,
} from '../api/models';
import { MetricsTableComponent } from '../shared/components/metrics-table/metrics-table.component';
import {
  TimeSeriesChartComponent,
  TimeSeriesChartSeries,
  TimeSeriesPoint,
} from '../shared/components/time-series-chart/time-series-chart.component';
import { WsService, WsConnectionState } from '../ws.service';
import { observeBacktestRunProgress } from '../ws';

interface BacktestProgressState {
  status: string | null;
  progress: number | null;
  stage: string | null;
}

@Component({
  standalone: true,
  selector: 'app-backtest-run-detail-page',
  imports: [CommonModule, RouterLink, TimeSeriesChartComponent, MetricsTableComponent],
  templateUrl: './run-detail.page.html',
  styleUrls: ['./run-detail.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunDetailPage implements OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(BacktestsApi);
  private readonly ws = inject(WsService);

  readonly runId = signal<string | null>(null);
  readonly run = signal<BacktestRunDetailDto | null>(null);
  readonly metrics = signal<BacktestRunMetricsDto | null>(null);
  readonly summary = signal<BacktestRunSummaryMetricDto[]>([]);
  readonly tradeStats = signal<BacktestTradeStatDto[]>([]);
  readonly progress = signal<BacktestProgressState>({ status: null, progress: null, stage: null });
  readonly wsState = signal<WsConnectionState>('connecting');
  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly actionMessage = signal<string | null>(null);
  readonly isDownloadingReport = signal(false);
  readonly isExportingTrades = signal(false);
  readonly isArchiving = signal(false);

  private progressSubscription: Subscription | null = null;
  private progressStateSubscription: Subscription | null = null;

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe(params => {
      const id = params.get('id');
      this.runId.set(id);
      if (!id) {
        this.error.set('Missing backtest run identifier.');
        return;
      }
      this.fetchRun(id);
      this.connectProgress(id);
    });
  }

  readonly hasMetrics = computed(() => {
    const current = this.metrics();
    return !!current && (current.equityCurve.length > 0 || current.drawdownCurve.length > 0);
  });

  readonly equitySeries = computed<TimeSeriesChartSeries[]>(() => {
    const current = this.metrics();
    if (!current) {
      return [];
    }
    return [
      {
        id: 'equity',
        name: 'Equity curve',
        color: '#38bdf8',
        data: this.toSeriesPoints(current.equityCurve),
      },
    ];
  });

  readonly drawdownSeries = computed<TimeSeriesChartSeries[]>(() => {
    const current = this.metrics();
    if (!current) {
      return [];
    }
    return [
      {
        id: 'drawdown',
        name: 'Drawdown',
        color: '#f97316',
        data: this.toSeriesPoints(current.drawdownCurve),
      },
    ];
  });

  readonly progressPercentDisplay = computed(() => {
    const value = this.progress().progress;
    return typeof value === 'number' && !Number.isNaN(value) ? Math.min(Math.max(value, 0), 100) : null;
  });

  readonly canDownload = computed(() => {
    const run = this.run();
    return !!run && ['completed', 'archived'].includes(run.status ?? '');
  });

  readonly canArchive = computed(() => {
    const run = this.run();
    if (!run) {
      return false;
    }
    if (run.archivedAt) {
      return false;
    }
    return run.status === 'completed';
  });

  readonly drawdownFormatter = (value: number) => `${value.toFixed(2)}%`;

  ngOnDestroy(): void {
    this.disposeProgressSubscriptions();
  }

  refresh(): void {
    const id = this.runId();
    if (!id) {
      return;
    }
    this.fetchRun(id);
  }

  downloadReport(): void {
    const id = this.runId();
    if (!id || this.isDownloadingReport()) {
      return;
    }
    this.isDownloadingReport.set(true);
    this.actionMessage.set(null);
    this.api.downloadReport(id).subscribe({
      next: blob => this.triggerDownload(blob, `${id}-report.zip`),
      error: err => {
        console.error(err);
        this.actionMessage.set('Failed to download report.');
        this.isDownloadingReport.set(false);
      },
      complete: () => this.isDownloadingReport.set(false),
    });
  }

  exportTrades(): void {
    const id = this.runId();
    if (!id || this.isExportingTrades()) {
      return;
    }
    this.isExportingTrades.set(true);
    this.actionMessage.set(null);
    this.api.exportTrades(id).subscribe({
      next: blob => this.triggerDownload(blob, `${id}-trades.csv`),
      error: err => {
        console.error(err);
        this.actionMessage.set('Failed to export trades.');
        this.isExportingTrades.set(false);
      },
      complete: () => this.isExportingTrades.set(false),
    });
  }

  archiveRun(): void {
    const id = this.runId();
    if (!id || this.isArchiving()) {
      return;
    }
    this.isArchiving.set(true);
    this.actionMessage.set(null);
    this.api.archiveRun(id).subscribe({
      next: () => {
        const current = this.run();
        if (current) {
          this.run.set({ ...current, status: 'archived', archivedAt: new Date().toISOString() });
        }
        this.actionMessage.set('Run archived successfully.');
      },
      error: err => {
        console.error(err);
        this.actionMessage.set('Failed to archive run.');
        this.isArchiving.set(false);
      },
      complete: () => this.isArchiving.set(false),
    });
  }

  private fetchRun(runId: string): void {
    this.isLoading.set(true);
    this.error.set(null);
    this.api.getRun(runId).subscribe({
      next: response => {
        const { run } = response;
        this.run.set(run);
        const metrics = run.metrics ?? { equityCurve: [], drawdownCurve: [], tradeStats: [] };
        this.metrics.set(metrics);
        this.summary.set(run.summary ?? []);
        this.tradeStats.set(metrics.tradeStats ?? []);
        this.progress.set({
          status: run.status ?? null,
          progress: run.progress ?? null,
          stage: run.progressStage ?? null,
        });
      },
      error: err => {
        console.error(err);
        this.error.set('Failed to load backtest run.');
        this.isLoading.set(false);
      },
      complete: () => this.isLoading.set(false),
    });
  }

  private connectProgress(runId: string): void {
    this.disposeProgressSubscriptions();
    const { progress$, state$ } = observeBacktestRunProgress(runId, this.ws);
    this.progressSubscription = progress$.subscribe({
      next: message => this.applyProgress(message),
      error: err => {
        console.error(err);
        this.wsState.set('disconnected');
      },
    });
    this.progressStateSubscription = state$.subscribe(state => this.wsState.set(state));
  }

  private disposeProgressSubscriptions(): void {
    this.progressSubscription?.unsubscribe();
    this.progressSubscription = null;
    this.progressStateSubscription?.unsubscribe();
    this.progressStateSubscription = null;
  }

  private applyProgress(message: BacktestRunProgressMessage): void {
    const currentProgress = this.progress();
    this.progress.set({
      status: message.status ?? currentProgress.status,
      progress:
        typeof message.progress === 'number' ? message.progress : currentProgress.progress ?? null,
      stage: message.stage ?? currentProgress.stage,
    });

    if (message.metrics) {
      const existing = this.metrics() ?? { equityCurve: [], drawdownCurve: [], tradeStats: [] };
      const coercePoints = (points?: BacktestMetricPointDto[] | null) =>
        Array.isArray(points) ? points : existing.equityCurve;
      const coerceDrawdown = (points?: BacktestMetricPointDto[] | null) =>
        Array.isArray(points) ? points : existing.drawdownCurve;
      const coerceTradeStats = (rows?: BacktestTradeStatDto[] | null) =>
        Array.isArray(rows) ? rows : existing.tradeStats;

      const merged: BacktestRunMetricsDto = {
        equityCurve: coercePoints(message.metrics.equityCurve),
        drawdownCurve: coerceDrawdown(message.metrics.drawdownCurve),
        tradeStats: coerceTradeStats(message.metrics.tradeStats),
      };
      this.metrics.set(merged);
      this.tradeStats.set(merged.tradeStats);
    }

    if (Array.isArray(message.summary)) {
      this.summary.set(message.summary);
    }

    const run = this.run();
    if (run && message.status) {
      this.run.set({ ...run, status: message.status });
    }
  }

  private toSeriesPoints(points: BacktestMetricPointDto[]): TimeSeriesPoint[] {
    return points ?? [];
  }

  private triggerDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }
}
