import { Injectable, OnDestroy, Signal, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { NodeMetricKey, NodeMetricPoint, NodeMetricsSnapshot } from '../../../api/models';
import { WsConnectionState, WsService } from '../../../ws.service';
import { observeNodeMetricsStream } from '../../../ws';
import { NodeMetricSeriesPayload } from '../../../ws/nodes.stream';
import { MetricsChartSeries } from '../metrics-chart/metrics-chart.component';

export type NodeMetricsPeriod = '30m' | '2h' | '6h' | '12h' | 'all';

interface PeriodOption {
  readonly value: NodeMetricsPeriod;
  readonly label: string;
  readonly durationMs: number | null;
}

interface MetricDefinition {
  readonly key: NodeMetricKey;
  readonly label: string;
  readonly shortLabel: string;
  readonly unit?: string;
  readonly color: string;
  readonly digits?: number;
  readonly changeDigits?: number;
}

export interface NodeMetricCard {
  readonly key: NodeMetricKey;
  readonly label: string;
  readonly value: string;
  readonly changeLabel: string;
  readonly positive: boolean | null;
  readonly color: string;
}

const PERIOD_OPTIONS: readonly PeriodOption[] = [
  { value: '30m', label: '30m', durationMs: 30 * 60 * 1000 },
  { value: '2h', label: '2h', durationMs: 2 * 60 * 60 * 1000 },
  { value: '6h', label: '6h', durationMs: 6 * 60 * 60 * 1000 },
  { value: '12h', label: '12h', durationMs: 12 * 60 * 60 * 1000 },
  { value: 'all', label: 'All', durationMs: null },
];

const METRIC_DEFINITIONS: readonly MetricDefinition[] = [
  { key: 'pnl', label: 'Profit & Loss', shortLabel: 'PnL', unit: '$', color: '#38bdf8', digits: 2 },
  { key: 'latency_ms', label: 'Latency', shortLabel: 'Latency', unit: 'ms', color: '#f97316', digits: 1 },
  { key: 'cpu_percent', label: 'CPU usage', shortLabel: 'CPU', unit: '%', color: '#a855f7', digits: 1 },
  { key: 'memory_mb', label: 'Memory', shortLabel: 'Memory', unit: 'MB', color: '#34d399', digits: 0, changeDigits: 0 },
];

function formatNumber(value: number, fractionDigits: number | undefined): string {
  if (Number.isNaN(value)) {
    return '–';
  }
  const digits = fractionDigits ?? (Math.abs(value) >= 100 ? 0 : 2);
  return value.toFixed(digits);
}

function formatMetricValue(value: number | undefined, metric: MetricDefinition): string {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '–';
  }
  const formatted = formatNumber(value, metric.digits);
  if (!metric.unit) {
    return formatted;
  }
  if (metric.unit === '$') {
    const sign = value >= 0 ? '' : '-';
    return `${sign}${metric.unit}${Math.abs(value).toFixed(metric.digits ?? 2)}`;
  }
  if (metric.unit === '%') {
    return `${formatted}${metric.unit}`;
  }
  return `${formatted} ${metric.unit}`;
}

function formatChange(value: number | null, metric: MetricDefinition): { label: string; positive: boolean | null } {
  if (value === null || Number.isNaN(value)) {
    return { label: '–', positive: null };
  }
  const digits = metric.changeDigits ?? metric.digits ?? (Math.abs(value) >= 100 ? 0 : 2);
  const prefix = value > 0 ? '+' : value < 0 ? '−' : '';
  const absolute = Math.abs(value).toFixed(digits);
  if (!metric.unit) {
    return { label: `${prefix}${absolute}`, positive: value > 0 ? true : value < 0 ? false : null };
  }
  if (metric.unit === '$') {
    return { label: `${prefix}$${absolute}`, positive: value > 0 ? true : value < 0 ? false : null };
  }
  if (metric.unit === '%') {
    return {
      label: `${prefix}${absolute}${metric.unit}`,
      positive: value > 0 ? true : value < 0 ? false : null,
    };
  }
  return {
    label: `${prefix}${absolute} ${metric.unit}`,
    positive: value > 0 ? true : value < 0 ? false : null,
  };
}

const EMPTY_SERIES: Record<NodeMetricKey, NodeMetricPoint[]> = {
  pnl: [],
  latency_ms: [],
  cpu_percent: [],
  memory_mb: [],
};

@Injectable()
export class NodeMetricsStore implements OnDestroy {
  private readonly ws = inject(WsService);

  private streamSub: Subscription | null = null;
  private stateSub: Subscription | null = null;
  private currentNodeId: string | null = null;

  readonly streamState = signal<WsConnectionState>('connecting');
  readonly series = signal<Record<NodeMetricKey, NodeMetricPoint[]>>({ ...EMPTY_SERIES });
  readonly latest = signal<NodeMetricsSnapshot | null>(null);
  readonly selectedMetrics = signal<readonly NodeMetricKey[]>(['pnl', 'latency_ms']);
  readonly period = signal<NodeMetricsPeriod>('2h');

  readonly periodOptions = PERIOD_OPTIONS;
  readonly metricDefinitions = METRIC_DEFINITIONS;

  readonly filteredSeries: Signal<Record<NodeMetricKey, NodeMetricPoint[]>> = computed(() => {
    const selectedPeriod = this.period();
    const option = PERIOD_OPTIONS.find((item) => item.value === selectedPeriod);
    const duration = option?.durationMs ?? null;
    if (!duration) {
      return this.series();
    }
    const cutoff = Date.now() - duration;
    const source = this.series();
    const result: Record<NodeMetricKey, NodeMetricPoint[]> = {
      pnl: [],
      latency_ms: [],
      cpu_percent: [],
      memory_mb: [],
    };
    (Object.keys(source) as NodeMetricKey[]).forEach((key) => {
      result[key] = source[key].filter((point) => Date.parse(point.timestamp) >= cutoff);
    });
    return result;
  });

  readonly chartSeries: Signal<MetricsChartSeries[]> = computed(() => {
    const selected = this.selectedMetrics();
    const series = this.filteredSeries();
    return METRIC_DEFINITIONS.filter((definition) => selected.includes(definition.key)).map(
      (definition) => ({
        id: definition.key,
        name: definition.shortLabel,
        color: definition.color,
        data: series[definition.key] ?? [],
      }),
    );
  });

  readonly cards: Signal<NodeMetricCard[]> = computed(() => {
    const series = this.filteredSeries();
    const latest = this.latest();
    return METRIC_DEFINITIONS.map((definition) => {
      const points = series[definition.key] ?? [];
      const first = points[0]?.value ?? null;
      const last = points[points.length - 1]?.value ?? null;
      const latestValue = last ?? latest?.[definition.key] ?? null;
      const formattedValue =
        latestValue === null ? '–' : formatMetricValue(latestValue, definition);
      let change: number | null = null;
      if (first !== null && last !== null && points.length > 1) {
        change = last - first;
      }
      const { label: changeLabel, positive } = formatChange(change, definition);
      return {
        key: definition.key,
        label: definition.label,
        value: formattedValue,
        changeLabel,
        positive,
        color: definition.color,
      };
    });
  });

  connect(nodeId: string | null): void {
    if (nodeId === this.currentNodeId) {
      return;
    }
    this.dispose();
    this.currentNodeId = nodeId;
    if (!nodeId) {
      this.series.set({ ...EMPTY_SERIES });
      this.latest.set(null);
      this.streamState.set('disconnected');
      return;
    }

    const { metrics$, state$ } = observeNodeMetricsStream(nodeId, this.ws);
    this.streamState.set('connecting');
    this.stateSub = state$.subscribe((state) => this.streamState.set(state));
    this.streamSub = metrics$.subscribe({
      next: (payload: NodeMetricSeriesPayload) => {
        this.series.set(payload.series);
        this.latest.set(payload.latest ?? null);
      },
      error: (err) => {
        console.error(err);
        this.streamState.set('disconnected');
      },
    });
  }

  disconnect(): void {
    this.dispose();
    this.series.set({ ...EMPTY_SERIES });
    this.latest.set(null);
    this.streamState.set('disconnected');
    this.currentNodeId = null;
  }

  setPeriod(period: NodeMetricsPeriod): void {
    if (this.period() !== period) {
      this.period.set(period);
    }
  }

  toggleMetric(metric: NodeMetricKey): void {
    const current = this.selectedMetrics();
    if (current.includes(metric)) {
      if (current.length === 1) {
        return;
      }
      this.selectedMetrics.set(current.filter((item) => item !== metric));
      return;
    }
    this.selectedMetrics.set([...current, metric]);
  }

  metricSelected(metric: NodeMetricKey): boolean {
    return this.selectedMetrics().includes(metric);
  }

  private dispose(): void {
    this.streamSub?.unsubscribe();
    this.stateSub?.unsubscribe();
    this.streamSub = null;
    this.stateSub = null;
  }

  ngOnDestroy(): void {
    this.dispose();
  }
}
