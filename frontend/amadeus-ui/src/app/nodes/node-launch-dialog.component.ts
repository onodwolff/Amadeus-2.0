import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
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
import {
  ApiKey,
  ExchangeDescriptor,
  NodeLaunchAdapterSelection,
  NodeLaunchConstraints,
  NodeLaunchRequest,
  NodeLaunchStrategy,
  NodeLaunchStrategyParameter,
  NodeMode,
} from '../api/models';
import { KeysApi } from '../api/clients/keys.api';
import { IntegrationsApi } from '../api/clients/integrations.api';

type AdapterFormGroup = FormGroup<{
  venue: FormControl<string>;
  alias: FormControl<string>;
  keyId: FormControl<string>;
  enableData: FormControl<boolean>;
  enableTrading: FormControl<boolean>;
  sandbox: FormControl<boolean>;
}>;

interface LaunchVenueOption {
  code: string;
  name: string;
  keys: ApiKey[];
}

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
  private readonly keysApi = inject(KeysApi);
  private readonly integrationsApi = inject(IntegrationsApi);

  readonly isOpen = signal(false);
  readonly currentStep = signal(0);
  readonly stepError = signal<string | null>(null);
  readonly submissionError = signal<string | null>(null);

  readonly apiKeys = signal<ApiKey[]>([]);
  readonly isKeysLoading = signal(false);
  readonly keysError = signal<string | null>(null);

  readonly exchanges = signal<ExchangeDescriptor[]>([]);
  readonly isExchangesLoading = signal(false);
  readonly exchangesError = signal<string | null>(null);

  private hasLoadedExchanges = false;

  readonly nodeTypeOptions: Array<{ value: NodeMode; label: string; description: string }> = [
    {
      value: 'backtest',
      label: 'Backtest bot',
      description: 'Launch a historical simulation with deterministic data replay.',
    },
    {
      value: 'sandbox',
      label: 'Sandbox bot',
      description: 'Connect to simulated adapters for paper trading workflows.',
    },
    {
      value: 'live',
      label: 'Live trading bot',
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

  readonly steps = [
    {
      key: 'type',
      title: 'Select bot mode',
      description: 'Choose between historical backtesting, sandbox simulation, or live execution.',
    },
    {
      key: 'strategy',
      title: 'Strategy configuration',
      description: 'Pick a strategy template and review its runtime parameters.',
    },
    {
      key: 'adapters',
      title: 'Exchanges & adapters',
      description: 'Select venues and assign saved API keys to enable data and trading adapters.',
    },
    {
      key: 'constraints',
      title: 'Launch constraints',
      description: 'Define guardrails such as runtime limits and auto-stop behaviour.',
    },
    {
      key: 'review',
      title: 'Review & launch',
      description: 'Verify configuration and submit the bot launch request.',
    },
  ] as const;

  readonly currentStepDescriptor = computed(() => {
    const fallback = this.steps[0];
    return this.steps[this.currentStep()] ?? fallback ?? {
      key: 'type',
      title: '',
      description: '',
    };
  });
  readonly selectedStrategyDescription = computed(() => {
    const id = this.form.controls.strategy.controls.id.value;
    const template = this.strategyTemplates.find((item) => item.id === id);
    return template?.description ?? 'Select a template';
  });
  readonly venueOptions = computed<LaunchVenueOption[]>(() => this.computeVenueOptions());

  readonly form = this.fb.nonNullable.group({
    nodeType: this.fb.nonNullable.control<NodeMode>('backtest'),
    strategy: this.fb.nonNullable.group({
      id: this.fb.nonNullable.control<string>(this.strategyTemplates[0]?.id ?? ''),
      name: this.fb.nonNullable.control<string>(this.strategyTemplates[0]?.name ?? ''),
      parameters: this.fb.array<FormGroup<{ key: FormControl<string>; value: FormControl<string> }>>([
        this.createStrategyParameterGroup('fast_window', '12'),
        this.createStrategyParameterGroup('slow_window', '26'),
      ]),
    }),
    adapters: this.fb.array<AdapterFormGroup>([]),
    constraints: this.fb.group({
      maxRuntimeMinutes: this.fb.control<number | null>(480, { validators: [Validators.min(1)] }),
      maxDrawdownPercent: this.fb.control<number | null>(20, {
        validators: [Validators.min(1), Validators.max(100)],
      }),
      autoStopOnError: this.fb.nonNullable.control<boolean>(true),
      concurrencyLimit: this.fb.control<number | null>(1, { validators: [Validators.min(1)] }),
    }),
  });

  constructor() {
    this.form.controls.nodeType.valueChanges.subscribe((mode) =>
      this.onNodeModeChanged((mode as NodeMode) ?? 'backtest'),
    );
  }

  open(initialType?: NodeMode): void {
    this.ensureExchangeCatalog();
    this.refreshKeys();

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

  adaptersArray(): FormArray<AdapterFormGroup> {
    return this.form.controls.adapters;
  }

  adapterGroup(venue: string): AdapterFormGroup | null {
    return (
      this.adaptersArray().controls.find(
        (group) => group.controls.venue.value === venue,
      ) || null
    );
  }

  isVenueSelected(venue: string): boolean {
    return this.adapterGroup(venue) !== null;
  }

  onVenueToggle(option: LaunchVenueOption, checked: boolean): void {
    const existing = this.adapterGroup(option.code);
    if (checked) {
      if (existing) {
        return;
      }
      const defaultKey = option.keys[0]?.key_id ?? '';
      this.adaptersArray().push(
        this.createAdapterGroup({
          venue: option.code,
          alias: option.code.toLowerCase(),
          keyId: defaultKey,
          enableData: true,
          enableTrading: this.form.controls.nodeType.value === 'live',
          sandbox: this.form.controls.nodeType.value === 'sandbox',
        }),
      );
    } else if (existing) {
      const index = this.adaptersArray().controls.indexOf(existing);
      if (index >= 0) {
        this.adaptersArray().removeAt(index);
      }
    }
  }

  onAdapterKeyChanged(venue: string, keyId: string): void {
    const group = this.adapterGroup(venue);
    if (!group) {
      return;
    }
    group.controls.keyId.setValue(keyId ?? '');
  }

  addStrategyParameter(key = '', value = ''): void {
    this.strategyParameters().push(this.createStrategyParameterGroup(key, value));
  }

  removeStrategyParameter(index: number): void {
    this.strategyParameters().removeAt(index);
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
    template.defaults.forEach((param) =>
      params.push(this.createStrategyParameterGroup(param.key, param.value)),
    );
  }

  private ensureExchangeCatalog(): void {
    if (this.hasLoadedExchanges) {
      return;
    }
    this.hasLoadedExchanges = true;
    this.isExchangesLoading.set(true);
    this.exchangesError.set(null);
    this.integrationsApi.listExchanges().subscribe({
      next: (response) => {
        const normalized = (response.exchanges ?? [])
          .map((entry) => ({
            code: (entry.code || '').toUpperCase(),
            name: entry.name || entry.code || '',
          }))
          .filter((entry) => entry.code.length > 0);
        normalized.sort((a, b) => a.name.localeCompare(b.name));
        this.exchanges.set(normalized);
        this.isExchangesLoading.set(false);
      },
      error: (error) => {
        console.error(error);
        this.exchangesError.set('Unable to load exchange catalog.');
        this.isExchangesLoading.set(false);
      },
    });
  }

  private refreshKeys(): void {
    this.isKeysLoading.set(true);
    this.keysError.set(null);
    this.keysApi.listKeys().subscribe({
      next: (response) => {
        this.apiKeys.set(response.keys ?? []);
        this.isKeysLoading.set(false);
        this.reconcileAdaptersWithKeys();
      },
      error: (error) => {
        console.error(error);
        this.keysError.set('Unable to load API keys.');
        this.isKeysLoading.set(false);
      },
    });
  }

  private computeVenueOptions(): LaunchVenueOption[] {
    const keysByVenue = new Map<string, ApiKey[]>();
    for (const key of this.apiKeys()) {
      const venue = (key.venue || '').toUpperCase();
      if (!venue) {
        continue;
      }
      if (!keysByVenue.has(venue)) {
        keysByVenue.set(venue, []);
      }
      keysByVenue.get(venue)!.push(key);
    }

    const map = new Map<string, LaunchVenueOption>();
    for (const exchange of this.exchanges()) {
      const code = (exchange.code || '').toUpperCase();
      if (!code) {
        continue;
      }
      map.set(code, {
        code,
        name: exchange.name || code,
        keys: keysByVenue.get(code) ?? [],
      });
    }

    for (const [venue, list] of keysByVenue.entries()) {
      if (map.has(venue)) {
        map.get(venue)!.keys = list;
      } else {
        map.set(venue, { code: venue, name: venue, keys: list });
      }
    }

    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }

  private reconcileAdaptersWithKeys(): void {
    const available = new Set(this.apiKeys().map((key) => key.key_id));
    this.adaptersArray().controls.forEach((group) => {
      const keyId = group.controls.keyId.value;
      if (keyId && !available.has(keyId)) {
        group.controls.keyId.setValue('');
      }
    });
  }

  private onNodeModeChanged(mode: NodeMode): void {
    const isSandbox = mode === 'sandbox';
    const allowTrading = mode === 'live';
    this.adaptersArray().controls.forEach((group) => {
      group.controls.sandbox.setValue(isSandbox);
      if (!allowTrading && group.controls.enableTrading.value) {
        group.controls.enableTrading.setValue(false);
      }
    });
  }

  private createStrategyParameterGroup(
    key = '',
    value = '',
  ): FormGroup<{ key: FormControl<string>; value: FormControl<string> }> {
    return this.fb.nonNullable.group({
      key: this.fb.nonNullable.control<string>(key, { validators: [Validators.required] }),
      value: this.fb.nonNullable.control<string>(value, { validators: [Validators.required] }),
    });
  }

  private createAdapterGroup(
    preset: Partial<NodeLaunchAdapterSelection> = {},
  ): AdapterFormGroup {
    const mode = this.form.controls.nodeType.value;
    const alias = (preset.alias ?? preset.venue?.toLowerCase() ?? '').trim();
    return this.fb.nonNullable.group({
      venue: this.fb.nonNullable.control<string>(preset.venue ?? '', {
        validators: [Validators.required],
      }),
      alias: this.fb.nonNullable.control<string>(alias),
      keyId: this.fb.nonNullable.control<string>(preset.keyId ?? ''),
      enableData: this.fb.nonNullable.control<boolean>(
        preset.enableData ?? true,
      ),
      enableTrading: this.fb.nonNullable.control<boolean>(
        preset.enableTrading ?? mode === 'live',
      ),
      sandbox: this.fb.nonNullable.control<boolean>(
        preset.sandbox ?? mode === 'sandbox',
      ),
    });
  }

  private resetForm(initialType: NodeMode): void {
    this.form.controls.nodeType.setValue(initialType);

    const defaultTemplate = this.strategyTemplates[0];
    this.form.controls.strategy.controls.id.setValue(defaultTemplate?.id ?? '');
    this.form.controls.strategy.controls.name.setValue(defaultTemplate?.name ?? '');
    const params = this.strategyParameters();
    params.clear();
    (defaultTemplate?.defaults ?? []).forEach((param) =>
      params.push(this.createStrategyParameterGroup(param.key, param.value)),
    );

    const adapters = this.adaptersArray();
    adapters.clear();
    adapters.markAsPristine();
    adapters.markAsUntouched();

    this.form.controls.constraints.patchValue({
      maxRuntimeMinutes:
        initialType === 'backtest' ? 480 : initialType === 'sandbox' ? 720 : null,
      maxDrawdownPercent: 20,
      autoStopOnError: true,
      concurrencyLimit:
        initialType === 'live' ? 1 : initialType === 'sandbox' ? 1 : null,
    });

    this.onNodeModeChanged(initialType);
  }

  private validateCurrentStep(isSubmit = false): boolean {
    const step = this.currentStep();
    this.stepError.set(null);
    switch (step) {
      case 0: {
        const control = this.form.controls.nodeType;
        control.markAsTouched();
        if (!control.value) {
          this.stepError.set('Please select the bot execution mode.');
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
        const adapters = this.adaptersArray();
        adapters.controls.forEach((group) => group.markAllAsTouched());
        const mode = this.form.controls.nodeType.value;
        if (mode === 'live') {
          if (adapters.length === 0) {
            this.stepError.set('Select at least one exchange for live bots.');
            return false;
          }
          const missingKeys = adapters.controls.some((group) => !group.controls.keyId.value);
          if (missingKeys) {
            this.stepError.set('Assign an API key to each selected exchange.');
            return false;
          }
        }
        return true;
      }
      case 3: {
        const constraints = this.form.controls.constraints;
        constraints.markAllAsTouched();
        if (!constraints.valid) {
          this.stepError.set('Review the constraint values; some entries are invalid.');
          return false;
        }
        return true;
      }
      case 4: {
        if (!isSubmit) {
          return true;
        }
        if (!this.form.valid) {
          this.stepError.set('Resolve validation errors before launching the bot.');
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

    const adapters: NodeLaunchAdapterSelection[] = this.adaptersArray().controls.map((group) => ({
      venue: group.controls.venue.value,
      alias: group.controls.alias.value?.trim() ?? '',
      keyId: group.controls.keyId.value?.trim() ?? '',
      enableData: group.controls.enableData.value,
      enableTrading: group.controls.enableTrading.value,
      sandbox: group.controls.sandbox.value,
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
      adapters,
      constraints,
      dataSources: [],
      keyReferences: [],
    };
  }
}
