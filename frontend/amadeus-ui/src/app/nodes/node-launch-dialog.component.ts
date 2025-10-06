import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Output, computed, inject, signal } from '@angular/core';
import {
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import {
  NodeLaunchConstraints,
  NodeLaunchDataSource,
  NodeLaunchKeyReference,
  NodeLaunchRequest,
  NodeLaunchStrategy,
  NodeLaunchStrategyParameter,
  NodeMode,
} from '../api/models';

type DataSourceFormGroup = FormGroup<{
  id: FormControl<string>;
  label: FormControl<string>;
  type: FormControl<string>;
  mode: FormControl<string>;
  enabled: FormControl<boolean>;
}>;

type KeyReferenceFormGroup = FormGroup<{
  alias: FormControl<string>;
  keyId: FormControl<string>;
  required: FormControl<boolean>;
}>;

@Component({
  selector: 'app-node-launch-dialog',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './node-launch-dialog.component.html',
  styleUrls: ['./node-launch-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodeLaunchDialogComponent {
  @Output() readonly launch = new EventEmitter<NodeLaunchRequest>();
  @Output() readonly closed = new EventEmitter<void>();

  private readonly fb = inject(FormBuilder);

  readonly isOpen = signal(false);
  readonly currentStep = signal(0);
  readonly stepError = signal<string | null>(null);
  readonly submissionError = signal<string | null>(null);

  readonly nodeTypeOptions: Array<{ value: NodeMode; label: string; description: string }> = [
    {
      value: 'backtest',
      label: 'Backtest node',
      description: 'Launch a historical simulation with deterministic data replay.',
    },
    {
      value: 'sandbox',
      label: 'Sandbox trading node',
      description: 'Connect to simulated adapters for paper trading workflows.',
    },
    {
      value: 'live',
      label: 'Live trading node',
      description: 'Connect to live market adapters and execute strategies in production.',
    },
  ];

  readonly strategyTemplates: Array<{
    id: string;
    name: string;
    description: string;
    defaults: NodeLaunchStrategyParameter[];
  }> = [
    {
      id: 'ema_cross',
      name: 'EMA Cross',
      description: 'Trend following crossover strategy for spot venues.',
      defaults: [
        { key: 'fast_window', value: '12' },
        { key: 'slow_window', value: '26' },
        { key: 'symbol', value: 'BTCUSDT' },
      ],
    },
    {
      id: 'mean_reversion',
      name: 'Mean Reversion',
      description: 'Range trading logic with volatility filter.',
      defaults: [
        { key: 'lookback', value: '48' },
        { key: 'threshold', value: '1.5' },
        { key: 'symbol', value: 'ETHUSDT' },
      ],
    },
    {
      id: 'market_maker',
      name: 'Market Maker',
      description: 'Two-sided quoting with configurable skew.',
      defaults: [
        { key: 'base_spread_bps', value: '5' },
        { key: 'inventory_target', value: '0.0' },
        { key: 'symbol', value: 'BTCUSDT' },
      ],
    },
  ];

  readonly dataSourcePresets: Array<Partial<NodeLaunchDataSource>> = [
    { id: 'binance-btcusdt-1m', label: 'Binance BTC/USDT 1m klines', type: 'historical', mode: 'read' },
    { id: 'binance-btcusdt-live', label: 'Binance BTC/USDT live trades', type: 'live', mode: 'read' },
    { id: 'binance-order-entry', label: 'Binance order entry', type: 'live', mode: 'write' },
    { id: 'binance-sandbox-market', label: 'Binance sandbox market feed', type: 'synthetic', mode: 'read' },
    { id: 'binance-sandbox-entry', label: 'Binance sandbox order entry', type: 'synthetic', mode: 'write' },
  ];

  readonly availableKeys: Array<{ id: string; alias: string; description: string }> = [
    { id: 'binance-primary', alias: 'Binance primary key', description: 'Full trading permissions' },
    { id: 'binance-readonly', alias: 'Binance readonly key', description: 'Market data only' },
    { id: 'paper-trading', alias: 'Paper trading sandbox', description: 'Isolated API credentials' },
  ];

  readonly steps = [
    {
      key: 'type',
      title: 'Select node type',
      description: 'Choose between historical backtesting, sandbox, or live trading execution.',
    },
    {
      key: 'strategy',
      title: 'Strategy configuration',
      description: 'Pick a strategy template and review its runtime parameters.',
    },
    {
      key: 'dataSources',
      title: 'Market data & adapters',
      description: 'Select market data feeds and execution adapters required by the node.',
    },
    {
      key: 'keys',
      title: 'Credential references',
      description: 'Link API keys or secrets provisioned in the key management module.',
    },
    {
      key: 'constraints',
      title: 'Launch constraints',
      description: 'Define guardrails such as runtime limits and auto-stop behaviour.',
    },
    {
      key: 'review',
      title: 'Review & launch',
      description: 'Verify configuration and submit the node launch request.',
    },
  ] as const;

  readonly currentStepDescriptor = computed(() => this.steps[this.currentStep()]);
  readonly selectedStrategyDescription = computed(() => {
    const id = this.form.controls.strategy.controls.id.value;
    const template = this.strategyTemplates.find((item) => item.id === id);
    return template?.description ?? 'Select a template';
  });

  readonly form = this.fb.nonNullable.group({
    nodeType: this.fb.nonNullable.control<NodeMode>('backtest'),
    strategy: this.fb.nonNullable.group({
      id: this.fb.nonNullable.control<string>(this.strategyTemplates[0]?.id ?? ''),
      name: this.fb.nonNullable.control<string>('EMA Cross'),
      parameters: this.fb.array<FormGroup<{ key: FormControl<string>; value: FormControl<string> }>>([
        this.createStrategyParameterGroup('fast_window', '12'),
        this.createStrategyParameterGroup('slow_window', '26'),
      ]),
    }),
    dataSources: this.fb.array<DataSourceFormGroup>([
      this.createDataSourceGroup({ id: 'binance-btcusdt-1m', label: 'Binance BTC/USDT 1m klines', type: 'historical', mode: 'read' }),
    ]),
    keyReferences: this.fb.array<KeyReferenceFormGroup>([
      this.createKeyReferenceGroup({ alias: 'Binance primary key', keyId: 'binance-primary', required: true }),
    ]),
    constraints: this.fb.group({
      maxRuntimeMinutes: this.fb.control<number | null>(480, { validators: [Validators.min(1)] }),
      maxDrawdownPercent: this.fb.control<number | null>(20, {
        validators: [Validators.min(1), Validators.max(100)],
      }),
      autoStopOnError: this.fb.nonNullable.control<boolean>(true),
      concurrencyLimit: this.fb.control<number | null>(1, { validators: [Validators.min(1)] }),
    }),
  });

  open(initialType?: NodeMode): void {
    this.isOpen.set(true);
    this.currentStep.set(0);
    this.stepError.set(null);
    this.submissionError.set(null);
    this.resetForm(initialType ?? 'backtest');
  }

  close(): void {
    this.isOpen.set(false);
    this.closed.emit();
  }

  nextStep(): void {
    if (!this.validateCurrentStep()) {
      return;
    }
    this.currentStep.update((index) => Math.min(index + 1, this.steps.length - 1));
    this.stepError.set(null);
  }

  previousStep(): void {
    this.currentStep.update((index) => Math.max(index - 1, 0));
    this.stepError.set(null);
  }

  submit(): void {
    if (!this.validateCurrentStep(true)) {
      return;
    }
    const payload = this.buildPayload();
    this.launch.emit(payload);
  }

  setSubmissionError(message: string): void {
    this.submissionError.set(message);
  }

  clearSubmissionError(): void {
    this.submissionError.set(null);
  }

  markAsCompleted(): void {
    this.close();
  }

  strategyParameters(): FormArray<FormGroup<{ key: FormControl<string>; value: FormControl<string> }>> {
    return this.form.controls.strategy.controls.parameters;
  }

  dataSourcesArray(): FormArray<DataSourceFormGroup> {
    return this.form.controls.dataSources;
  }

  keyReferencesArray(): FormArray<KeyReferenceFormGroup> {
    return this.form.controls.keyReferences;
  }

  addStrategyParameter(key = '', value = ''): void {
    this.strategyParameters().push(this.createStrategyParameterGroup(key, value));
  }

  removeStrategyParameter(index: number): void {
    this.strategyParameters().removeAt(index);
  }

  addDataSource(preset?: Partial<NodeLaunchDataSource>): void {
    this.dataSourcesArray().push(this.createDataSourceGroup(preset));
  }

  removeDataSource(index: number): void {
    this.dataSourcesArray().removeAt(index);
  }

  addKeyReference(preset?: Partial<NodeLaunchKeyReference>): void {
    this.keyReferencesArray().push(this.createKeyReferenceGroup(preset));
  }

  removeKeyReference(index: number): void {
    this.keyReferencesArray().removeAt(index);
  }

  onTemplateChange(event: Event): void {
    const target = event.target as HTMLSelectElement | null;
    if (!target) {
      return;
    }
    this.selectStrategy(target.value);
  }

  selectStrategy(templateId: string): void {
    const template = this.strategyTemplates.find((item) => item.id === templateId);
    if (!template) {
      return;
    }
    this.form.controls.strategy.controls.id.setValue(template.id);
    this.form.controls.strategy.controls.name.setValue(template.name);
    const params = this.strategyParameters();
    params.clear();
    template.defaults.forEach((param) => params.push(this.createStrategyParameterGroup(param.key, param.value)));
  }

  private createStrategyParameterGroup(key = '', value = ''): FormGroup<{ key: FormControl<string>; value: FormControl<string> }> {
    return this.fb.nonNullable.group({
      key: this.fb.nonNullable.control<string>(key, { validators: [Validators.required] }),
      value: this.fb.nonNullable.control<string>(value, { validators: [Validators.required] }),
    });
  }

  private createDataSourceGroup(
    preset: Partial<NodeLaunchDataSource> = {},
  ): DataSourceFormGroup {
    return this.fb.nonNullable.group({
      id: this.fb.nonNullable.control<string>(preset.id ?? ''),
      label: this.fb.nonNullable.control<string>(preset.label ?? ''),
      type: this.fb.nonNullable.control<string>(preset.type ?? 'historical'),
      mode: this.fb.nonNullable.control<string>(preset.mode ?? 'read'),
      enabled: this.fb.nonNullable.control<boolean>(preset.enabled ?? true),
    });
  }

  private createKeyReferenceGroup(
    preset: Partial<NodeLaunchKeyReference> = {},
  ): KeyReferenceFormGroup {
    return this.fb.nonNullable.group({
      alias: this.fb.nonNullable.control<string>(preset.alias ?? '', { validators: [Validators.required] }),
      keyId: this.fb.nonNullable.control<string>(preset.keyId ?? '', { validators: [Validators.required] }),
      required: this.fb.nonNullable.control<boolean>(preset.required ?? true),
    });
  }

  private resetForm(initialType: NodeMode): void {
    this.form.controls.nodeType.setValue(initialType);
    const defaultTemplate = this.strategyTemplates[0];
    this.form.controls.strategy.controls.id.setValue(defaultTemplate?.id ?? '');
    this.form.controls.strategy.controls.name.setValue(defaultTemplate?.name ?? '');
    const params = this.strategyParameters();
    params.clear();
    (defaultTemplate?.defaults ?? []).forEach((param) => params.push(this.createStrategyParameterGroup(param.key, param.value)));

    const dataSources = this.dataSourcesArray();
    dataSources.clear();
    if (initialType === 'live') {
      dataSources.push(
        this.createDataSourceGroup({ id: 'binance-btcusdt-live', label: 'Binance BTC/USDT live trades', type: 'live', mode: 'read' }),
      );
      dataSources.push(
        this.createDataSourceGroup({ id: 'binance-order-entry', label: 'Binance order entry', type: 'live', mode: 'write' }),
      );
    } else if (initialType === 'sandbox') {
      dataSources.push(
        this.createDataSourceGroup({
          id: 'binance-sandbox-market',
          label: 'Binance sandbox market feed',
          type: 'synthetic',
          mode: 'read',
        }),
      );
      dataSources.push(
        this.createDataSourceGroup({
          id: 'binance-sandbox-entry',
          label: 'Binance sandbox order entry',
          type: 'synthetic',
          mode: 'write',
        }),
      );
    } else {
      dataSources.push(
        this.createDataSourceGroup({ id: 'binance-btcusdt-1m', label: 'Binance BTC/USDT 1m klines', type: 'historical', mode: 'read' }),
      );
    }

    const keyRefs = this.keyReferencesArray();
    keyRefs.clear();
    if (initialType === 'sandbox') {
      keyRefs.push(this.createKeyReferenceGroup({ alias: 'Paper trading sandbox', keyId: 'paper-trading', required: true }));
    } else {
      keyRefs.push(this.createKeyReferenceGroup({ alias: 'Binance primary key', keyId: 'binance-primary', required: true }));
    }

    this.form.controls.constraints.patchValue({
      maxRuntimeMinutes: initialType === 'live' ? null : initialType === 'sandbox' ? 720 : 480,
      maxDrawdownPercent: 20,
      autoStopOnError: true,
      concurrencyLimit: initialType === 'live' ? 1 : initialType === 'sandbox' ? 1 : null,
    });
  }

  private validateCurrentStep(isSubmit = false): boolean {
    const step = this.currentStep();
    this.stepError.set(null);
    switch (step) {
      case 0: {
        const control = this.form.controls.nodeType;
        control.markAsTouched();
        if (!control.value) {
          this.stepError.set('Please select the node execution mode.');
          return false;
        }
        return true;
      }
      case 1: {
        const strategy = this.form.controls.strategy;
        strategy.markAllAsTouched();
        if (!strategy.valid) {
          this.stepError.set('Fill in the required strategy information.');
          return false;
        }
        if (this.strategyParameters().length === 0) {
          this.stepError.set('Add at least one runtime parameter for the strategy.');
          return false;
        }
        return true;
      }
      case 2: {
        if (this.dataSourcesArray().length === 0) {
          this.stepError.set('Specify at least one data source or adapter.');
          return false;
        }
        this.dataSourcesArray().controls.forEach((group) => group.markAllAsTouched());
        if (!this.dataSourcesArray().valid) {
          this.stepError.set('Data source details are incomplete.');
          return false;
        }
        return true;
      }
      case 3: {
        this.keyReferencesArray().controls.forEach((group) => group.markAllAsTouched());
        if (this.keyReferencesArray().length === 0) {
          this.stepError.set('Provide at least one credential reference to authorise adapters.');
          return false;
        }
        if (!this.keyReferencesArray().valid) {
          this.stepError.set('Credential references are incomplete.');
          return false;
        }
        return true;
      }
      case 4: {
        const constraints = this.form.controls.constraints;
        constraints.markAllAsTouched();
        if (!constraints.valid) {
          this.stepError.set('Review the constraint values; some entries are invalid.');
          return false;
        }
        return true;
      }
      case 5: {
        if (!isSubmit) {
          return true;
        }
        if (!this.form.valid) {
          this.stepError.set('Resolve validation errors before launching the node.');
          return false;
        }
        return true;
      }
      default:
        return true;
    }
  }

  private buildPayload(): NodeLaunchRequest {
    const formValue = this.form.getRawValue();

    const strategy: NodeLaunchStrategy = {
      id: formValue.strategy.id,
      name: formValue.strategy.name,
      parameters: formValue.strategy.parameters.map<NodeLaunchStrategyParameter>((group) => ({
        key: group.key,
        value: group.value,
      })),
    };

    const dataSources: NodeLaunchDataSource[] = formValue.dataSources.map((source) => ({
      id: source.id,
      label: source.label,
      type: source.type,
      mode: source.mode,
      enabled: source.enabled,
    }));

    const keyReferences: NodeLaunchKeyReference[] = formValue.keyReferences.map((key) => ({
      alias: key.alias,
      keyId: key.keyId,
      required: key.required,
    }));

    const constraints: NodeLaunchConstraints = {
      maxRuntimeMinutes: formValue.constraints.maxRuntimeMinutes ?? null,
      maxDrawdownPercent: formValue.constraints.maxDrawdownPercent ?? null,
      autoStopOnError: formValue.constraints.autoStopOnError,
      concurrencyLimit: formValue.constraints.concurrencyLimit ?? null,
    };

    return {
      type: formValue.nodeType,
      strategy,
      dataSources,
      keyReferences,
      constraints,
    };
  }
}
