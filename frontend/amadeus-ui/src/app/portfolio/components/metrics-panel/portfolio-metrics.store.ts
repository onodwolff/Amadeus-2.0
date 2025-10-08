import { Injectable, Signal, computed, inject, signal } from '@angular/core';
import { PortfolioApi } from '../../../api/clients/portfolio.api';
import { PortfolioHistoryPoint, Position } from '../../../api/models';
import {
  TimeSeriesChartSeries,
  TimeSeriesPoint,
} from '../../../shared/components/time-series-chart/time-series-chart.component';

export type PortfolioMetricsPeriod = '1W' | '1M' | '3M' | 'ALL';

interface PeriodOption {
  readonly value: PortfolioMetricsPeriod;
  readonly label: string;
  readonly durationMs: number | null;
}

interface RealizedUnrealizedPoint {
  readonly timestamp: string;
  readonly realized: number;
  readonly unrealized: number;
}

const PERIOD_OPTIONS: readonly PeriodOption[] = [
  { value: '1W', label: '1W', durationMs: 7 * 24 * 60 * 60 * 1000 },
  { value: '1M', label: '1M', durationMs: 30 * 24 * 60 * 60 * 1000 },
  { value: '3M', label: '3M', durationMs: 90 * 24 * 60 * 60 * 1000 },
  { value: 'ALL', label: 'All', durationMs: null },
];

const ASSET_CLASS_COLORS: Record<string, string> = {
  Crypto: '#38bdf8',
  FX: '#f97316',
  Equities: '#a855f7',
  Futures: '#facc15',
  Commodities: '#f59e0b',
  'Fixed Income': '#34d399',
  Other: '#f472b6',
};

const FALLBACK_COLORS = ['#22d3ee', '#fb7185', '#c084fc', '#fbbf24', '#4ade80', '#60a5fa'];
const CRYPTO_TOKENS = ['BTC', 'ETH', 'SOL', 'ADA', 'XRP', 'DOT', 'DOGE', 'AVAX', 'MATIC', 'USDT', 'USDC'];
const EQUITY_TOKENS = ['AAPL', 'TSLA', 'MSFT', 'AMZN', 'GOOG', 'META', 'NVDA'];
const FX_CODES = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF'];
const MAX_HISTORY_POINTS = 720;

@Injectable()
export class PortfolioMetricsStore {
  private readonly portfolioApi = inject(PortfolioApi);
  private hasRequestedHistory = false;

  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly history = signal<PortfolioHistoryPoint[]>([]);
  readonly selectedPeriod = signal<PortfolioMetricsPeriod>('1M');

  readonly periodOptions = PERIOD_OPTIONS;

  readonly filteredHistory: Signal<PortfolioHistoryPoint[]> = computed(() => {
    const history = this.history();
    if (history.length === 0) {
      return [];
    }
    const period = this.selectedPeriod();
    const option = PERIOD_OPTIONS.find(item => item.value === period);
    if (!option || option.durationMs === null) {
      return history;
    }
    const cutoff = Date.now() - option.durationMs;
    return history.filter(sample => Date.parse(sample.timestamp) >= cutoff);
  });

  readonly dailySnapshots: Signal<PortfolioHistoryPoint[]> = computed(() => {
    const history = this.filteredHistory();
    if (history.length === 0) {
      return [];
    }
    const grouped = new Map<string, PortfolioHistoryPoint>();
    for (const sample of history) {
      const dayKey = sample.timestamp.slice(0, 10);
      const existing = grouped.get(dayKey);
      if (!existing || Date.parse(sample.timestamp) > Date.parse(existing.timestamp)) {
        grouped.set(dayKey, sample);
      }
    }
    return Array.from(grouped.values()).sort(
      (a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp),
    );
  });

  readonly dailyPnlPoints: Signal<TimeSeriesPoint[]> = computed(() => {
    const snapshots = this.dailySnapshots();
    if (snapshots.length === 0) {
      return [];
    }
    const result: TimeSeriesPoint[] = [];
    let previousEquity: number | null = null;
    for (const snapshot of snapshots) {
      const pnl = previousEquity === null ? 0 : snapshot.equity - previousEquity;
      result.push({ timestamp: snapshot.timestamp, value: Number(pnl.toFixed(2)) });
      previousEquity = snapshot.equity;
    }
    return result;
  });

  readonly dailyPnlSeries: Signal<TimeSeriesChartSeries[]> = computed(() => {
    const data = this.dailyPnlPoints();
    if (data.length === 0) {
      return [];
    }
    return [
      {
        id: 'portfolio-daily-pnl',
        name: 'Daily PnL',
        color: '#38bdf8',
        data,
      },
    ];
  });

  readonly realizedUnrealizedPoints: Signal<RealizedUnrealizedPoint[]> = computed(() => {
    const snapshots = this.dailySnapshots();
    if (snapshots.length === 0) {
      return [];
    }
    return snapshots.map(snapshot => ({
      timestamp: snapshot.timestamp,
      realized: Number((snapshot.realized ?? 0).toFixed(2)),
      unrealized: Number((snapshot.unrealized ?? 0).toFixed(2)),
    }));
  });

  readonly realizedUnrealizedSeries: Signal<TimeSeriesChartSeries[]> = computed(() => {
    const points = this.realizedUnrealizedPoints();
    if (points.length === 0) {
      return [];
    }
    return [
      {
        id: 'portfolio-realized',
        name: 'Realized PnL',
        color: '#34d399',
        data: points.map(point => ({ timestamp: point.timestamp, value: point.realized })),
      },
      {
        id: 'portfolio-unrealized',
        name: 'Unrealized PnL',
        color: '#f97316',
        data: points.map(point => ({ timestamp: point.timestamp, value: point.unrealized })),
      },
    ];
  });

  readonly assetClasses: Signal<string[]> = computed(() => {
    const history = this.history();
    const set = new Set<string>();
    for (const sample of history) {
      Object.keys(sample.exposures ?? {}).forEach(key => set.add(key));
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  });

  readonly exposureSeries: Signal<TimeSeriesChartSeries[]> = computed(() => {
    const snapshots = this.dailySnapshots();
    if (snapshots.length === 0) {
      return [];
    }
    const classes = this.assetClasses();
    const activeClasses = classes.filter(className =>
      snapshots.some(snapshot => Math.abs(snapshot.exposures?.[className] ?? 0) > 0.01),
    );
    return activeClasses.map((className, index) => {
      const data = snapshots.map(snapshot => ({
        timestamp: snapshot.timestamp,
        value: Number(((snapshot.exposures ?? {})[className] ?? 0).toFixed(2)),
      }));
      return {
        id: `portfolio-exposure-${className.toLowerCase()}`,
        name: className,
        color: this.colorForAssetClass(className, index),
        data,
      };
    });
  });

  readonly dailyPnlTable = computed(() =>
    this.dailyPnlPoints().map(point => ({ timestamp: point.timestamp, pnl: point.value })),
  );

  readonly realizedUnrealizedTable = computed(() => this.realizedUnrealizedPoints());

  readonly exposureTable = computed(() => {
    const snapshots = this.dailySnapshots();
    const classes = this.assetClasses();
    if (snapshots.length === 0 || classes.length === 0) {
      return [] as { timestamp: string; values: Record<string, number> }[];
    }
    const activeClasses = classes.filter(className =>
      snapshots.some(snapshot => Math.abs(snapshot.exposures?.[className] ?? 0) > 0.01),
    );
    return snapshots.map(snapshot => {
      const values: Record<string, number> = {};
      for (const className of activeClasses) {
        values[className] = Number(((snapshot.exposures ?? {})[className] ?? 0).toFixed(2));
      }
      return { timestamp: snapshot.timestamp, values };
    });
  });

  loadHistory(limit = MAX_HISTORY_POINTS): void {
    if (this.hasRequestedHistory) {
      return;
    }
    this.hasRequestedHistory = true;
    this.isLoading.set(true);
    this.error.set(null);
    this.portfolioApi.getPortfolioHistory(limit).subscribe({
      next: response => {
        const history = response?.history ?? [];
        this.mergeHistory(history);
        this.isLoading.set(false);
      },
      error: err => {
        console.error('Failed to load portfolio history', err);
        this.error.set('Failed to load historical metrics.');
        this.isLoading.set(false);
        this.hasRequestedHistory = false;
      },
    });
  }

  setPeriod(period: PortfolioMetricsPeriod): void {
    this.selectedPeriod.set(period);
  }

  ingestPositions(
    positions: readonly Position[] | null | undefined,
    timestamp?: string,
    equity?: number | null,
  ): void {
    const entries = positions ?? [];
    const realized = entries.reduce((total, position) => total + (position.realized_pnl ?? 0), 0);
    const unrealized = entries.reduce(
      (total, position) => total + (position.unrealized_pnl ?? 0),
      0,
    );
    const historyEntry: PortfolioHistoryPoint = {
      timestamp: timestamp || new Date().toISOString(),
      equity: this.resolveEquity(equity, realized, unrealized),
      realized: Number(realized.toFixed(2)),
      unrealized: Number(unrealized.toFixed(2)),
      exposures: this.buildExposureMap(entries),
    };
    this.mergeHistory([historyEntry]);
  }

  private mergeHistory(samples: readonly PortfolioHistoryPoint[]): void {
    if (!samples || samples.length === 0) {
      return;
    }
    this.history.update(current => {
      const map = new Map<string, PortfolioHistoryPoint>();
      for (const entry of current) {
        map.set(entry.timestamp, {
          ...entry,
          exposures: { ...(entry.exposures ?? {}) },
        });
      }
      for (const entry of samples) {
        map.set(entry.timestamp, {
          ...entry,
          exposures: { ...(entry.exposures ?? {}) },
        });
      }
      const merged = Array.from(map.values()).sort(
        (a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp),
      );
      return merged.slice(-MAX_HISTORY_POINTS);
    });
  }

  private resolveEquity(
    equity: number | null | undefined,
    realized: number,
    unrealized: number,
  ): number {
    if (typeof equity === 'number' && Number.isFinite(equity)) {
      return Number(equity.toFixed(2));
    }
    const history = this.history();
    const last = history[history.length - 1];
    if (last) {
      return last.equity;
    }
    return Number((realized + unrealized).toFixed(2));
  }

  private buildExposureMap(positions: readonly Position[]): Record<string, number> {
    const exposures = new Map<string, number>();
    for (const position of positions) {
      const mark = position.mark_price ?? position.average_price ?? 0;
      const quantity = position.quantity ?? 0;
      const exposure = quantity * mark;
      if (!Number.isFinite(exposure)) {
        continue;
      }
      const assetClass = this.inferAssetClass(position.symbol);
      exposures.set(assetClass, (exposures.get(assetClass) ?? 0) + exposure);
    }
    return Object.fromEntries(
      Array.from(exposures.entries()).map(([key, value]) => [key, Number(value.toFixed(2))]),
    );
  }

  private inferAssetClass(symbol: string | null | undefined): string {
    if (!symbol) {
      return 'Other';
    }
    const normalized = symbol.toUpperCase();
    if (CRYPTO_TOKENS.some(token => normalized.includes(token))) {
      return 'Crypto';
    }
    if (FX_CODES.some(code => normalized.startsWith(code) || normalized.endsWith(code))) {
      return 'FX';
    }
    if (EQUITY_TOKENS.some(token => normalized.includes(token))) {
      return 'Equities';
    }
    if (normalized.includes('FUT') || normalized.includes('PERP')) {
      return 'Futures';
    }
    if (normalized.includes('OIL') || normalized.includes('GOLD') || normalized.includes('WTI')) {
      return 'Commodities';
    }
    if (normalized.includes('BOND') || normalized.includes('NOTE')) {
      return 'Fixed Income';
    }
    return 'Other';
  }

  private colorForAssetClass(name: string | undefined, index: number): string {
    const key = name ?? 'Other';
    const mapped = ASSET_CLASS_COLORS[key];
    if (mapped) {
      return mapped;
    }
    const fallback = FALLBACK_COLORS[index % FALLBACK_COLORS.length] ?? '#64748b';
    return fallback;
  }
}
