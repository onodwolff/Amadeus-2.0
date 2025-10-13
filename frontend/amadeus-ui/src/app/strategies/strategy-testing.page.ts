import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { Subscription, finalize, switchMap, takeWhile, tap, timer } from 'rxjs';

import { StrategyTestsApi } from '../api/clients';
import type {
  StrategyOptimisationDirection,
  StrategyOptimisationPlan,
  StrategyTestResultDto,
  StrategyTestRunDto,
  StrategyTestRunRequest,
} from '../api/models';
import {
  MetricsTableComponent,
  MetricsTableRow,
} from '../shared/components/metrics-table/metrics-table.component';
import {
  TimeSeriesChartComponent,
  TimeSeriesChartSeries,
} from '../shared/components/time-series-chart/time-series-chart.component';
import { AuthStateService } from '../shared/auth/auth-state.service';

type ParameterRangeGroup = FormGroup<{
  key: FormControl<string>;
  values: FormControl<string>;
}>;

type StrategyTemplate = {
  id: string;
  name: string;
  description: string;
  ranges: { key: string; values: string }[];
};

type DatasetOption = {
  id: string;
  name: string;
  venue: string;
  barInterval: string;
  instrument: string;
  description: string;
  start: string;
  end: string;
};

@Component({
  standalone: true,
  selector: 'app-strategy-testing-page',
  imports: [
    CommonModule,
    ReactiveFormsModule,
    TimeSeriesChartComponent,
    MetricsTableComponent,
  ],
  templateUrl: './strategy-testing.page.html',
  styleUrls: ['./strategy-testing.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StrategyTestingPage implements OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(StrategyTestsApi);
  protected readonly authState = inject(AuthStateService);

  private pollSub?: Subscription;

  readonly isSubmitting = signal(false);
  readonly submissionError = signal<string | null>(null);
  readonly activeRun = signal<StrategyTestRunDto | null>(null);
  readonly runHistory = signal<StrategyTestRunDto[]>([]);

  readonly strategyTemplates: StrategyTemplate[] = [
    {
      id: 'ema_cross',
      name: 'EMA Cross',
      description: 'Optimise fast/slow EMA windows and symbol selection.',
      ranges: [
        { key: 'fast_window', values: '8,12,16' },
        { key: 'slow_window', values: '21,34,55' },
        { key: 'symbol', values: 'BTCUSDT,ETHUSDT,SOLUSDT' },
      ],
    },
    {
      id: 'mean_reversion',
      name: 'Mean Reversion',
      description: 'Grid search oscillator thresholds and lookback window.',
      ranges: [
        { key: 'lookback', values: '24,36,48' },
        { key: 'threshold', values: '1.2,1.4,1.6' },
        { key: 'symbol', values: 'ETHUSDT,BNBUSDT' },
      ],
    },
    {
      id: 'breakout',
      name: 'Momentum Breakout',
      description: 'Tune breakout window and risk multiplier for volatility regimes.',
      ranges: [
        { key: 'window', values: '48,72,96' },
        { key: 'risk_multiplier', values: '1.4,1.8,2.2' },
        { key: 'symbol', values: 'BTCUSDT,SOLUSDT,AVAXUSDT' },
      ],
    },
  ];

  readonly datasetOptions: DatasetOption[] = [
    {
      id: 'binance-btcusdt-1m-2023',
      name: 'Binance BTC/USDT (1m, 2023)',
      venue: 'BINANCE',
      barInterval: '1m',
      instrument: 'BTCUSDT',
      description: 'One year of minute bars for BTC/USDT from Binance spot.',
      start: '2023-01-01T00:00:00Z',
      end: '2023-12-31T23:59:00Z',
    },
    {
      id: 'binance-ethusdt-5m-2022',
      name: 'Binance ETH/USDT (5m, 2022)',
      venue: 'BINANCE',
      barInterval: '5m',
      instrument: 'ETHUSDT',
      description: 'Five minute candles covering 2022 for ETH/USDT.',
      start: '2022-01-01T00:00:00Z',
      end: '2022-12-31T23:59:00Z',
    },
    {
      id: 'okx-btcusdt-1m-q1-2024',
      name: 'OKX BTC/USDT (1m, Q1 2024)',
      venue: 'OKX',
      barInterval: '1m',
      instrument: 'BTCUSDT',
      description: 'Quarter one 2024 sample with depth enriched bars from OKX.',
      start: '2024-01-01T00:00:00Z',
      end: '2024-03-31T23:59:00Z',
    },
  ];

  private readonly templateDefaults = this.createTemplateDefaults(this.strategyTemplates[0]);
  private readonly datasetDefaults = this.createDatasetDefaults(this.datasetOptions[0]);

  readonly form = this.fb.nonNullable.group({
    name: this.fb.nonNullable.control('Strategy optimisation run', [
      Validators.required,
      Validators.maxLength(120),
    ]),
    strategy: this.fb.nonNullable.group({
      id: this.fb.nonNullable.control(this.templateDefaults.id, Validators.required),
      name: this.fb.nonNullable.control(this.templateDefaults.name, Validators.required),
      description: this.fb.nonNullable.control(this.templateDefaults.description),
    }),
    parameters: this.fb.array<ParameterRangeGroup>(
      this.templateDefaults.ranges.map(range => this.createParameterGroup(range)),
    ),
    dataset: this.fb.nonNullable.group({
      id: this.fb.nonNullable.control(this.datasetDefaults.id, Validators.required),
      name: this.fb.nonNullable.control(this.datasetDefaults.name, Validators.required),
      venue: this.fb.nonNullable.control(this.datasetDefaults.venue, Validators.required),
      barInterval: this.fb.nonNullable.control(
        this.datasetDefaults.barInterval,
        Validators.required,
      ),
      instrument: this.fb.nonNullable.control(
        this.datasetDefaults.instrument,
        Validators.required,
      ),
      description: this.fb.nonNullable.control(this.datasetDefaults.description),
      start: this.fb.nonNullable.control(
        this.formatDateTimeLocal(new Date(this.datasetDefaults.start)),
        Validators.required,
      ),
      end: this.fb.nonNullable.control(
        this.formatDateTimeLocal(new Date(this.datasetDefaults.end)),
        Validators.required,
      ),
    }),
    plan: this.fb.nonNullable.control<StrategyOptimisationPlan>('grid'),
    sampleCount: this.fb.control<number | null>(null, Validators.min(1)),
    maxParallel: this.fb.control<number | null>(2, [Validators.min(1)]),
    optimisationMetric: this.fb.nonNullable.control('sharpe_ratio'),
    optimisationDirection: this.fb.nonNullable.control<StrategyOptimisationDirection>('maximize'),
    randomSeed: this.fb.control<number | null>(null),
    engine: this.fb.nonNullable.group({
      initialBalance: this.fb.nonNullable.control(100_000, [Validators.required, Validators.min(0)]),
      baseCurrency: this.fb.nonNullable.control('USDT', Validators.required),
      slippageBps: this.fb.nonNullable.control(1, [Validators.required, Validators.min(0)]),
      commissionBps: this.fb.nonNullable.control(5, [Validators.required, Validators.min(0)]),
    }),
  });

  readonly parameterControls = computed(() => this.parameters.controls);

  readonly optimisationSeries = computed<TimeSeriesChartSeries[]>(() => {
    const run = this.activeRun();
    if (!run?.results || !run.optimisationMetric) {
      return [];
    }
    const data = run.results
      .filter(result => result.optimisationScore != null && !!result.completedAt)
      .map(result => ({
        timestamp: result.completedAt as string,
        value: Number(result.optimisationScore),
      }))
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

    if (data.length === 0) {
      return [];
    }

    return [
      {
        id: 'optimisation_score',
        name: `${run.optimisationMetric ?? 'score'}`,
        color: '#60a5fa',
        data,
      },
    ];
  });

  readonly bestResultMetrics = computed<MetricsTableRow[]>(() => {
    const run = this.activeRun();
    const best = run?.bestResult;
    if (!run || !best || !best.metrics) {
      return [];
    }
    const metricEntries: MetricsTableRow[] = [];
    if (best.optimisationScore != null) {
      metricEntries.push({
        label: `Optimisation score (${run.optimisationMetric ?? 'metric'})`,
        value: best.optimisationScore.toFixed(4),
      });
    }
    const totalReturn = asNumber(best.metrics['total_return']);
    if (totalReturn != null) {
      metricEntries.push({ label: 'Total return', value: `${(totalReturn * 100).toFixed(2)} %` });
    }
    const sharpe = asNumber(best.metrics['sharpe_ratio']);
    if (sharpe != null) {
      metricEntries.push({ label: 'Sharpe ratio', value: sharpe.toFixed(2) });
    }
    const drawdown = asNumber(best.metrics['max_drawdown']);
    if (drawdown != null) {
      metricEntries.push({ label: 'Max drawdown', value: `${(drawdown * 100).toFixed(2)} %` });
    }
    return metricEntries;
  });

  constructor() {
    this.loadRunHistory();
  }

  get parameters(): FormArray<ParameterRangeGroup> {
    return this.form.controls.parameters;
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  onStrategyChange(templateId: string): void {
    const template = this.strategyTemplates.find(entry => entry.id === templateId);
    if (!template) {
      return;
    }
    this.form.controls.strategy.controls.name.setValue(template.name);
    this.form.controls.strategy.controls.description.setValue(template.description);
    this.parameters.clear();
    template.ranges.forEach(range => this.parameters.push(this.createParameterGroup(range)));
  }

  getSelectValue(event: Event): string {
    const target = event.target as HTMLSelectElement | null;
    return target?.value ?? '';
  }

  onDatasetChange(datasetId: string): void {
    const dataset = this.datasetOptions.find(entry => entry.id === datasetId);
    if (!dataset) {
      return;
    }
    const datasetGroup = this.form.controls.dataset;
    datasetGroup.controls.name.setValue(dataset.name);
    datasetGroup.controls.venue.setValue(dataset.venue);
    datasetGroup.controls.barInterval.setValue(dataset.barInterval);
    datasetGroup.controls.instrument.setValue(dataset.instrument);
    datasetGroup.controls.description.setValue(dataset.description);
    datasetGroup.controls.start.setValue(this.formatDateTimeLocal(new Date(dataset.start)));
    datasetGroup.controls.end.setValue(this.formatDateTimeLocal(new Date(dataset.end)));
  }

  addParameter(): void {
    this.parameters.push(
      this.createParameterGroup({ key: 'parameter', values: 'value1,value2,value3' }),
    );
  }

  removeParameter(index: number): void {
    this.parameters.removeAt(index);
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const payload = this.buildRequestPayload();
    this.isSubmitting.set(true);
    this.submissionError.set(null);

    this.api
      .createRun(payload)
      .pipe(
        finalize(() => this.isSubmitting.set(false)),
        tap(response => {
          this.activeRun.set(response.run);
          this.startPolling(response.run.id);
          this.loadRunHistory();
        }),
      )
      .subscribe({
        error: error => {
          const message = error?.error?.detail ?? error?.message ?? 'Failed to create optimisation run';
          this.submissionError.set(message);
        },
      });
  }

  trackResult = (_: number, item: StrategyTestResultDto) => item.id;
  trackParameter = (_: number, group: ParameterRangeGroup) => group.controls.key.value;
  trackRun = (_: number, run: StrategyTestRunDto) => run.id;

  private createParameterGroup(range: { key: string; values: string }): ParameterRangeGroup {
    return this.fb.nonNullable.group({
      key: this.fb.nonNullable.control(range.key, Validators.required),
      values: this.fb.nonNullable.control(range.values, Validators.required),
    });
  }

  private buildRequestPayload(): StrategyTestRunRequest {
    const formValue = this.form.getRawValue();
    const parameterSpace: Record<string, unknown[]> = {};
    const strategyParameters: { key: string; value: unknown }[] = [];

    for (const group of formValue.parameters) {
      const key = group.key.trim();
      const values = this.parseValues(group.values);
      if (!key || values.length === 0) {
        continue;
      }
      parameterSpace[`strategy.parameters.${key}`] = values;
      strategyParameters.push({ key, value: values[0] ?? '' });
    }

    const dataset = formValue.dataset;
    const dateRange = {
      start: this.toIso(dataset.start),
      end: this.toIso(dataset.end),
    };

    const baseConfig = {
      type: 'backtest',
      name: formValue.name,
      dateRange,
      strategy: {
        id: formValue.strategy.id,
        name: formValue.strategy.name,
        parameters: strategyParameters.map(entry => ({
          key: entry.key,
          value: entry.value,
        })),
      },
      dataSources: [
        {
          id: dataset.id,
          label: dataset.name,
          type: 'historical',
          mode: 'read',
          parameters: {
            venue: dataset.venue,
            instrument: dataset.instrument,
            barInterval: dataset.barInterval,
            dateRange,
          },
        },
      ],
      engine: {
        initialBalance: formValue.engine.initialBalance,
        baseCurrency: formValue.engine.baseCurrency,
        slippageBps: formValue.engine.slippageBps,
        commissionBps: formValue.engine.commissionBps,
      },
      constraints: { maxRuntimeMinutes: 480, autoStopOnError: true },
    };

    const plan = formValue.plan;
    const optimisationMetric = formValue.optimisationMetric ?? 'pnl';
    const payload: StrategyTestRunRequest = {
      name: formValue.name,
      baseConfig,
      parameterSpace,
      plan,
      optimisationDirection: formValue.optimisationDirection,
      optimisationMetric,
      ...(formValue.randomSeed !== null && formValue.randomSeed !== undefined
        ? { randomSeed: formValue.randomSeed }
        : {}),
    };

    if (plan === 'random') {
      if (formValue.sampleCount != null) {
        const sampleCount = Number(formValue.sampleCount);
        if (Number.isFinite(sampleCount)) {
          payload.sampleCount = sampleCount;
        }
      }
    }
    if (formValue.maxParallel != null) {
      payload.maxParallel = formValue.maxParallel;
    }

    return payload;
  }

  startPolling(runId: string): void {
    this.pollSub?.unsubscribe();
    this.pollSub = timer(0, 4000)
      .pipe(
        switchMap(() => this.api.getRun(runId)),
        tap(response => this.activeRun.set(response.run)),
        takeWhile(response => !['completed', 'failed'].includes(response.run.status), true),
        finalize(() => this.loadRunHistory()),
      )
      .subscribe();
  }

  private loadRunHistory(): void {
    this.api
      .listRuns()
      .pipe(tap(response => this.runHistory.set(response.runs)))
      .subscribe();
  }

  private parseValues(raw: string): unknown[] {
    return raw
      .split(',')
      .map(value => value.trim())
      .filter(value => value.length > 0)
      .map(value => {
        const numeric = Number(value);
        return Number.isFinite(numeric) && value !== '' ? numeric : value;
      });
  }

  private createTemplateDefaults(template: StrategyTemplate | undefined): StrategyTemplate {
    return {
      id: template?.id ?? '',
      name: template?.name ?? '',
      description: template?.description ?? '',
      ranges: Array.isArray(template?.ranges) ? template.ranges : [],
    };
  }

  private createDatasetDefaults(option: DatasetOption | undefined): DatasetOption {
    return {
      id: option?.id ?? '',
      name: option?.name ?? '',
      venue: option?.venue ?? '',
      barInterval: option?.barInterval ?? '',
      instrument: option?.instrument ?? '',
      description: option?.description ?? '',
      start: option?.start ?? '',
      end: option?.end ?? '',
    };
  }

  private formatDateTimeLocal(date: Date): string {
    if (Number.isNaN(date.getTime())) {
      return '';
    }
    const clone = new Date(date.getTime());
    clone.setMinutes(clone.getMinutes() - clone.getTimezoneOffset());
    return clone.toISOString().slice(0, 16);
  }

  private toIso(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toISOString();
  }
}

function asNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}
