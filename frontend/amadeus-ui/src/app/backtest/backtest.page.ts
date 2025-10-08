import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import {
  AbstractControl,
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
  ValidatorFn,
  Validators,
} from '@angular/forms';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';
import { BacktestsApi, DataApi } from '../api/clients';
import {
  BacktestDatasetDto,
  BacktestRunCreateRequest,
  BacktestStrategyParameterDto,
  HistoricalDatasetDto,
} from '../api/models';

type StrategyParameterGroup = FormGroup<{ key: FormControl<string>; value: FormControl<string> }>;

type DatasetOption = {
  id: string;
  name: string;
  venue: string;
  barInterval: string;
  instrument: string;
  description: string;
  start: string;
  end: string;
  status?: string;
};

type StrategyTemplate = {
  id: string;
  name: string;
  description: string;
  defaults: BacktestStrategyParameterDto[];
};

@Component({
  standalone: true,
  selector: 'app-backtest-page',
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './backtest.page.html',
  styleUrls: ['./backtest.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BacktestPage {
  private static readonly dateRangeValidator: ValidatorFn = (control: AbstractControl): ValidationErrors | null => {
    const group = control as FormGroup;
    const start = group.controls['start']?.value;
    const end = group.controls['end']?.value;

    if (!start || !end) {
      return null;
    }

    const startDate = new Date(start);
    const endDate = new Date(end);
    if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
      return { dateRange: true };
    }

    if (startDate >= endDate) {
      return { dateRange: true };
    }

    return null;
  };

  private readonly fb = inject(FormBuilder);
  private readonly api = inject(BacktestsApi);
  private readonly dataApi = inject(DataApi);
  private readonly router = inject(Router);

  readonly isSubmitting = signal(false);
  readonly submissionError = signal<string | null>(null);

  readonly strategyTemplates: StrategyTemplate[] = [
    {
      id: 'ema_cross',
      name: 'EMA Cross',
      description: 'Dual exponential moving average crossover tuned for trend continuation.',
      defaults: [
        { key: 'fast_window', value: '12' },
        { key: 'slow_window', value: '26' },
        { key: 'symbol', value: 'BTCUSDT' },
      ],
    },
    {
      id: 'mean_reversion',
      name: 'Mean Reversion',
      description: 'Oscillator driven regime model optimised for range bound markets.',
      defaults: [
        { key: 'lookback', value: '48' },
        { key: 'threshold', value: '1.4' },
        { key: 'symbol', value: 'ETHUSDT' },
      ],
    },
    {
      id: 'momentum_breakout',
      name: 'Momentum Breakout',
      description: 'Volatility scaled breakout logic with trailing risk controls.',
      defaults: [
        { key: 'window', value: '72' },
        { key: 'risk_multiplier', value: '1.8' },
        { key: 'symbol', value: 'SOLUSDT' },
      ],
    },
  ];

  private readonly fallbackDatasets: DatasetOption[] = [
    {
      id: 'binance-btcusdt-1m-2023',
      name: 'Binance BTC/USDT (1m, 2023)',
      venue: 'BINANCE',
      barInterval: '1m',
      instrument: 'BTCUSDT',
      description: 'Full year of 1 minute klines for BTC/USDT captured from Binance spot.',
      start: new Date('2023-01-01T00:00:00Z').toISOString(),
      end: new Date('2023-12-31T23:59:00Z').toISOString(),
      status: 'ready',
    },
    {
      id: 'binance-ethusdt-5m-2022',
      name: 'Binance ETH/USDT (5m, 2022)',
      venue: 'BINANCE',
      barInterval: '5m',
      instrument: 'ETHUSDT',
      description: 'ETH/USDT historical candles (5 minute) covering 2022.',
      start: new Date('2022-01-01T00:00:00Z').toISOString(),
      end: new Date('2022-12-31T23:59:00Z').toISOString(),
      status: 'ready',
    },
    {
      id: 'okx-btcusdt-1m-q1-2024',
      name: 'OKX BTC/USDT (1m, Q1 2024)',
      venue: 'OKX',
      barInterval: '1m',
      instrument: 'BTCUSDT',
      description: 'Quarter one 2024 sample with depth enriched bars from OKX.',
      start: new Date('2024-01-01T00:00:00Z').toISOString(),
      end: new Date('2024-03-31T23:59:00Z').toISOString(),
      status: 'ready',
    },
  ];

  private readonly initialDataset = this.ensureDataset(this.fallbackDatasets[0]);
  private readonly initialStrategy = this.ensureStrategy(this.strategyTemplates[0]);

  readonly datasets = signal<DatasetOption[]>([]);
  readonly datasetLoadError = signal<string | null>(null);
  readonly isLoadingDatasets = signal(false);

  private readonly defaultStart = this.formatDateTimeLocal(new Date(this.initialDataset.start));
  private readonly defaultEnd = this.formatDateTimeLocal(new Date(this.initialDataset.end));

  readonly form = this.fb.nonNullable.group({
    name: this.fb.nonNullable.control<string>('New backtest run', {
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    strategy: this.fb.nonNullable.group({
      id: this.fb.nonNullable.control<string>(this.initialStrategy.id, Validators.required),
      name: this.fb.nonNullable.control<string>(this.initialStrategy.name, Validators.required),
      parameters: this.fb.array<StrategyParameterGroup>(
        this.initialStrategy.defaults.map(param => this.createStrategyParameterGroup(param)),
      ),
    }),
    dataset: this.fb.nonNullable.group({
      id: this.fb.nonNullable.control<string>(this.initialDataset.id, Validators.required),
      name: this.fb.nonNullable.control<string>(this.initialDataset.name, Validators.required),
      venue: this.fb.nonNullable.control<string>(this.initialDataset.venue, Validators.required),
      barInterval: this.fb.nonNullable.control<string>(this.initialDataset.barInterval, Validators.required),
      instrument: this.fb.nonNullable.control<string>(this.initialDataset.instrument, Validators.required),
      start: this.fb.nonNullable.control<string>(this.initialDataset.start, Validators.required),
      end: this.fb.nonNullable.control<string>(this.initialDataset.end, Validators.required),
      status: this.fb.control<string | null>(this.initialDataset.status ?? null),
      description: this.fb.control<string>(this.initialDataset.description),
    }),
    dateRange: this.fb.nonNullable.group(
      {
        start: this.fb.nonNullable.control<string>(this.defaultStart, Validators.required),
        end: this.fb.nonNullable.control<string>(this.defaultEnd, Validators.required),
      },
      { validators: BacktestPage.dateRangeValidator },
    ),
    engine: this.fb.nonNullable.group({
      initialBalance: this.fb.nonNullable.control<number>(100_000, {
        validators: [Validators.required, Validators.min(0)],
      }),
      baseCurrency: this.fb.nonNullable.control<string>('USDT', Validators.required),
      slippageBps: this.fb.nonNullable.control<number>(1, {
        validators: [Validators.required, Validators.min(0)],
      }),
      commissionBps: this.fb.nonNullable.control<number>(5, {
        validators: [Validators.required, Validators.min(0)],
      }),
      warmupDays: this.fb.nonNullable.control<number>(14, {
        validators: [Validators.required, Validators.min(0)],
      }),
      engineVersion: this.fb.nonNullable.control<string>('v2.0'),
    }),
  });

  constructor() {
    this.applyDatasetOptions(this.fallbackDatasets);
    this.refreshDatasets();
  }

  get strategyParameters(): FormArray<StrategyParameterGroup> {
    return this.form.controls.strategy.controls.parameters;
  }

  addStrategyParameter(): void {
    this.strategyParameters.push(this.createStrategyParameterGroup({ key: '', value: '' }));
  }

  removeStrategyParameter(index: number): void {
    this.strategyParameters.removeAt(index);
  }

  refreshDatasets(): void {
    this.isLoadingDatasets.set(true);
    this.datasetLoadError.set(null);
    this.dataApi
      .listDatasets()
      .pipe(finalize(() => this.isLoadingDatasets.set(false)))
      .subscribe({
        next: response => {
          const remote = (response.datasets ?? []).map(item => this.mapDataset(item));
          if (remote.length) {
            this.applyDatasetOptions(remote);
          } else {
            this.applyDatasetOptions(this.fallbackDatasets);
          }
        },
        error: () => {
          this.datasetLoadError.set('Unable to load cached datasets. Showing defaults.');
          this.applyDatasetOptions(this.fallbackDatasets);
        },
      });
  }

  onStrategyTemplateSelect(templateId: string): void {
    const template = this.strategyTemplates.find(item => item.id === templateId);
    if (!template) {
      return;
    }

    this.form.controls.strategy.patchValue({
      id: template.id,
      name: template.name,
    });

    const parametersArray = this.form.controls.strategy.controls.parameters;
    parametersArray.clear();
    template.defaults.forEach(param => parametersArray.push(this.createStrategyParameterGroup(param)));
  }

  onDatasetSelect(datasetId: string): void {
    const option = this.datasets().find(item => item.id === datasetId);
    if (!option) {
      return;
    }

    this.setDataset(option);
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const payload = this.buildPayload();
    this.isSubmitting.set(true);
    this.submissionError.set(null);

    this.api
      .createRun(payload)
      .pipe(finalize(() => this.isSubmitting.set(false)))
      .subscribe({
        next: response => {
          const runId = response.run?.id;
          if (runId) {
            this.router.navigate(['/backtest', runId]).catch(() => undefined);
          } else {
            this.submissionError.set('Backtest run created but response did not include an identifier.');
          }
        },
        error: error => {
          const message = error?.error?.detail || error?.message || 'Failed to create backtest run.';
          this.submissionError.set(message);
        },
      });
  }

  trackByIndex(index: number): number {
    return index;
  }

  trackByDatasetId(_index: number, option: DatasetOption): string {
    return option.id;
  }

  private applyDatasetOptions(options: DatasetOption[]): void {
    const currentId = this.form.controls.dataset.controls.id.value;
    this.datasets.set(options);
    const nextOption = options.find(item => item.id === currentId) ?? options[0];
    if (nextOption) {
      this.setDataset(nextOption);
    }
  }

  private setDataset(option: DatasetOption): void {
    this.form.controls.dataset.patchValue({
      id: option.id,
      name: option.name,
      venue: option.venue,
      barInterval: option.barInterval,
      instrument: option.instrument,
      start: this.normalizeDateValue(option.start),
      end: this.normalizeDateValue(option.end),
      status: option.status ?? null,
      description: option.description,
    });

    this.form.controls.dateRange.patchValue({
      start: this.formatDateTimeLocal(new Date(option.start)),
      end: this.formatDateTimeLocal(new Date(option.end)),
    });
  }

  private mapDataset(dataset: HistoricalDatasetDto): DatasetOption {
    return {
      id: dataset.datasetId,
      name: `${dataset.venue} ${dataset.instrument} (${dataset.timeframe})`,
      venue: dataset.venue,
      barInterval: dataset.timeframe,
      instrument: dataset.instrument,
      description: dataset.source ? `${dataset.source} dataset` : 'Cached dataset',
      start: dataset.start,
      end: dataset.end,
      status: dataset.status,
    };
  }

  private buildPayload(): BacktestRunCreateRequest {
    const value = this.form.getRawValue();

    return {
      name: value.name,
      strategy: {
        id: value.strategy.id,
        name: value.strategy.name,
        parameters: value.strategy.parameters.map(param => ({
          key: param.key,
          value: param.value,
        })),
      },
      dataset: {
        id: value.dataset.id,
        name: value.dataset.name,
        venue: value.dataset.venue,
        barInterval: value.dataset.barInterval,
      description: value.dataset.description ?? '',
      instrument: value.dataset.instrument,
      start: this.normalizeDateValue(value.dataset.start),
      end: this.normalizeDateValue(value.dataset.end),
      ...this.optionalStatus(value.dataset.status),
    },
      dateRange: {
        start: this.normalizeDateValue(value.dateRange.start),
        end: this.normalizeDateValue(value.dateRange.end),
      },
      engine: {
        initialBalance: value.engine.initialBalance,
        baseCurrency: value.engine.baseCurrency,
        slippageBps: value.engine.slippageBps,
        commissionBps: value.engine.commissionBps,
        warmupDays: value.engine.warmupDays,
        engineVersion: value.engine.engineVersion,
      },
    };
  }

  private ensureDataset(option: DatasetOption | undefined): DatasetOption {
    if (!option) {
      throw new Error('Fallback datasets are not configured.');
    }
    return option;
  }

  private ensureStrategy(template: StrategyTemplate | undefined): StrategyTemplate {
    if (!template) {
      throw new Error('Strategy templates are not configured.');
    }
    return template;
  }

  private optionalStatus(status: string | null | undefined): Partial<BacktestDatasetDto> {
    if (!status) {
      return {};
    }
    return { status };
  }

  private createStrategyParameterGroup(parameter: BacktestStrategyParameterDto): StrategyParameterGroup {
    return this.fb.nonNullable.group({
      key: this.fb.nonNullable.control<string>(parameter.key, Validators.required),
      value: this.fb.nonNullable.control<string>(parameter.value, Validators.required),
    });
  }

  private formatDateTimeLocal(date: Date): string {
    const pad = (value: number) => `${value}`.padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(
      date.getMinutes(),
    )}`;
  }

  private normalizeDateValue(value: string): string {
    const date = new Date(value);
    if (isNaN(date.getTime())) {
      return value;
    }
    return date.toISOString();
  }
}
