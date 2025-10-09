import { CommonModule } from '@angular/common';
import {
  AbstractControl,
  FormArray,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { finalize } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RiskApi } from '../api/clients';
import {
  PositionLimitConfig,
  RiskLimit,
  RiskLimits,
  RiskModuleStatus,
  TradeLockConfig,
} from '../api/models';
import { NotificationService } from '../shared/notifications/notification.service';
import { RiskLimitBreachesWidgetComponent } from './components/limit-breaches-widget/limit-breaches-widget.component';
import { RiskCircuitBreakersWidgetComponent } from './components/circuit-breakers-widget/circuit-breakers-widget.component';
import { RiskMarginCallsWidgetComponent } from './components/margin-calls-widget/margin-calls-widget.component';

interface RiskEscalation {
  warn_after?: number;
  halt_after?: number;
  reset_minutes?: number;
}

type PositionLimitFormGroup = FormGroup<{
  venue: FormControl<string>;
  node: FormControl<string>;
  limit: FormControl<number>;
}>;

type TradeLockFormGroup = FormGroup<{
  venue: FormControl<string>;
  node: FormControl<string>;
  locked: FormControl<boolean>;
  reason: FormControl<string>;
}>;

type PositionLimitsModuleGroup = FormGroup<{
  enabled: FormControl<boolean>;
  status: FormControl<RiskModuleStatus>;
  limits: FormArray<PositionLimitFormGroup>;
}>;

type MaxLossModuleGroup = FormGroup<{
  enabled: FormControl<boolean>;
  status: FormControl<RiskModuleStatus>;
  daily: FormControl<number>;
  weekly: FormControl<number>;
}>;

type TradeLocksModuleGroup = FormGroup<{
  enabled: FormControl<boolean>;
  status: FormControl<RiskModuleStatus>;
  locks: FormArray<TradeLockFormGroup>;
}>;

type RiskEscalationFormGroup = FormGroup<{
  warn_after: FormControl<number>;
  halt_after: FormControl<number>;
  reset_minutes: FormControl<number>;
}>;

type RiskControlsModuleGroup = FormGroup<{
  halt_on_breach: FormControl<boolean>;
  notify_on_recovery: FormControl<boolean>;
  escalation: RiskEscalationFormGroup;
}>;

type RiskFormGroup = FormGroup<{
  positionLimits: PositionLimitsModuleGroup;
  maxLoss: MaxLossModuleGroup;
  tradeLocks: TradeLocksModuleGroup;
  controls: RiskControlsModuleGroup;
}>;

@Component({
  standalone: true,
  selector: 'app-risk-page',
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RiskLimitBreachesWidgetComponent,
    RiskCircuitBreakersWidgetComponent,
    RiskMarginCallsWidgetComponent,
  ],
  templateUrl: './risk.page.html',
  styleUrls: ['./risk.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskPage implements OnInit {
  private static readonly allowedStatuses: RiskModuleStatus[] = [
    'up_to_date',
    'syncing',
    'stale',
    'error',
  ];

  private static readonly maxLossRangeValidator = (control: AbstractControl) => {
    const group = control as MaxLossModuleGroup;
    const daily = Number(group.controls.daily.value);
    const weekly = Number(group.controls.weekly.value);

    if (!Number.isFinite(daily) || !Number.isFinite(weekly)) {
      return null;
    }

    if (weekly < daily) {
      return { weeklyLessThanDaily: true };
    }

    return null;
  };

  private static readonly tradeLockReasonValidator = (control: AbstractControl) => {
    const group = control as TradeLockFormGroup;
    const locked = group.controls.locked.value;
    const reason = group.controls.reason.value?.trim();
    if (locked && !reason) {
      return { reasonRequired: true };
    }
    return null;
  };

  private readonly fb = inject(FormBuilder);
  private readonly api = inject(RiskApi);
  private readonly notifications = inject(NotificationService);

  readonly isLoading = signal(true);
  readonly isSaving = signal(false);
  readonly loadError = signal<string | null>(null);
  readonly riskUsage = signal<RiskLimit[]>([]);
  readonly drawdownUsage = signal<RiskLimit[]>([]);
  readonly advancedControlsExpanded = signal(false);
  readonly advancedControlsPanelId = 'risk-controls-advanced';

  readonly moduleStatusOptions = RiskPage.allowedStatuses.map((value) => ({
    value,
    label:
      value === 'up_to_date'
        ? 'Up to date'
        : value === 'syncing'
        ? 'Syncing'
        : value === 'stale'
        ? 'Stale'
        : 'Error',
  }));

  readonly form: RiskFormGroup = this.createForm();

  readonly isPristine = computed(() => this.form.pristine);

  ngOnInit(): void {
    this.setupModuleToggle(this.positionLimitsGroup, ['enabled', 'status']);
    this.setupModuleToggle(this.maxLossGroup, ['enabled', 'status']);
    this.setupModuleToggle(this.tradeLocksGroup, ['enabled', 'status']);
    this.loadLimits();
  }

  get positionLimitsGroup(): PositionLimitsModuleGroup {
    return this.form.controls.positionLimits;
  }

  get maxLossGroup(): MaxLossModuleGroup {
    return this.form.controls.maxLoss;
  }

  get tradeLocksGroup(): TradeLocksModuleGroup {
    return this.form.controls.tradeLocks;
  }

  get controlsGroup(): RiskControlsModuleGroup {
    return this.form.controls.controls;
  }

  get positionLimitEntries(): FormArray<PositionLimitFormGroup> {
    return this.positionLimitsGroup.controls.limits;
  }

  get tradeLockEntries(): FormArray<TradeLockFormGroup> {
    return this.tradeLocksGroup.controls.locks;
  }

  statusLabel(status: RiskModuleStatus | null | undefined): string {
    const entry = this.moduleStatusOptions.find((item) => item.value === status);
    return entry?.label ?? 'Unknown';
  }

  statusClass(status: RiskModuleStatus | null | undefined): string {
    switch (status) {
      case 'up_to_date':
        return 'status-chip--success';
      case 'syncing':
        return 'status-chip--info';
      case 'error':
        return 'status-chip--error';
      default:
        return 'status-chip--warning';
    }
  }

  trackByIndex(index: number): number {
    return index;
  }

  hasError(control: AbstractControl | null, error: string): boolean {
    if (!control) {
      return false;
    }
    return control.hasError(error) && (control.dirty || control.touched);
  }

  toggleAdvancedControls(): void {
    this.advancedControlsExpanded.update((expanded) => !expanded);
  }

  addPositionLimit(): void {
    const group = this.createPositionLimitGroup();
    if (!this.positionLimitsGroup.controls.enabled.value) {
      group.disable({ emitEvent: false });
    }
    this.positionLimitEntries.push(group);
  }

  removePositionLimit(index: number): void {
    if (index < 0 || index >= this.positionLimitEntries.length) {
      return;
    }
    this.positionLimitEntries.removeAt(index);
    if (this.positionLimitEntries.length === 0) {
      this.addPositionLimit();
    }
  }

  addTradeLock(): void {
    const group = this.createTradeLockGroup();
    if (!this.tradeLocksGroup.controls.enabled.value) {
      group.disable({ emitEvent: false });
    }
    this.tradeLockEntries.push(group);
  }

  removeTradeLock(index: number): void {
    if (index < 0 || index >= this.tradeLockEntries.length) {
      return;
    }
    this.tradeLockEntries.removeAt(index);
    if (this.tradeLockEntries.length === 0) {
      this.addTradeLock();
    }
  }

  reload(): void {
    this.loadLimits();
  }

  onSubmit(): void {
    this.markAllAsTouched(this.form);
    if (this.controlsGroup.invalid && !this.advancedControlsExpanded()) {
      this.advancedControlsExpanded.set(true);
    }
    if (this.form.invalid) {
      this.notifications.warning('Resolve validation issues before saving.', 'Risk controls');
      return;
    }

    const payload = this.buildPayload();
    this.isSaving.set(true);
    this.api
      .updateRiskLimits(payload)
      .pipe(finalize(() => this.isSaving.set(false)))
      .subscribe({
        next: (response) => {
          if (response?.limits) {
            this.applyLimits(response.limits);
          }
          this.form.markAsPristine();
          this.notifications.success('Risk limits updated successfully.', 'Risk API');
          this.loadRiskSnapshot();
        },
        error: (err) => {
          console.error('Failed to update risk limits', err);
          this.notifications.error('Failed to update risk limits.', 'Risk API');
        },
      });
  }

  private loadLimits(): void {
    this.isLoading.set(true);
    this.loadError.set(null);
    this.api
      .getRiskLimits()
      .pipe(finalize(() => this.isLoading.set(false)))
      .subscribe({
        next: (response) => {
          if (!response?.limits) {
            this.loadError.set('Risk API returned an empty limits payload.');
            return;
          }
          this.applyLimits(response.limits);
          this.form.markAsPristine();
          this.loadRiskSnapshot();
        },
        error: (err) => {
          console.error('Failed to load risk limits', err);
          this.loadError.set('Unable to load risk limits from the gateway.');
        },
      });
  }

  private applyLimits(limits: RiskLimits): void {
    const positionLimits = this.normalizePositionLimits(limits.position_limits);
    const maxLoss = this.normalizeMaxLoss(limits.max_loss);
    const tradeLocks = this.normalizeTradeLocks(limits.trade_locks);
    const controls = this.normalizeControls(limits.controls);

    this.positionLimitsGroup.patchValue(
      {
        enabled: positionLimits.enabled,
        status: positionLimits.status,
      },
      { emitEvent: false },
    );
    this.syncPositionLimitEntries(positionLimits);

    this.maxLossGroup.patchValue(
      {
        enabled: maxLoss.enabled,
        status: maxLoss.status,
        daily: maxLoss.daily,
        weekly: maxLoss.weekly,
      },
      { emitEvent: false },
    );

    this.tradeLocksGroup.patchValue(
      {
        enabled: tradeLocks.enabled,
        status: tradeLocks.status,
      },
      { emitEvent: false },
    );
    this.syncTradeLockEntries(tradeLocks);

    this.controlsGroup.patchValue(
      {
        halt_on_breach: controls.halt_on_breach,
        notify_on_recovery: controls.notify_on_recovery,
        escalation: {
          warn_after: controls.escalation.warn_after,
          halt_after: controls.escalation.halt_after,
          reset_minutes: controls.escalation.reset_minutes,
        },
      },
      { emitEvent: false },
    );

    this.applyModuleEnabledState(this.positionLimitsGroup, positionLimits.enabled, ['enabled', 'status']);
    this.applyModuleEnabledState(this.maxLossGroup, maxLoss.enabled, ['enabled', 'status']);
    this.applyModuleEnabledState(this.tradeLocksGroup, tradeLocks.enabled, ['enabled', 'status']);
  }

  private normalizePositionLimits(module?: Partial<RiskLimits['position_limits']>): Required<RiskLimits['position_limits']> {
    return {
      enabled: module?.enabled ?? false,
      status: this.normalizeStatus(module?.status),
      limits: Array.isArray(module?.limits) ? module!.limits.map((item) => ({
        venue: item.venue ?? '',
        node: item.node ?? '',
        limit: typeof item.limit === 'number' ? item.limit : Number(item.limit ?? 0),
      })) : [],
    };
  }

  private normalizeMaxLoss(module?: Partial<RiskLimits['max_loss']>): Required<RiskLimits['max_loss']> {
    return {
      enabled: module?.enabled ?? false,
      status: this.normalizeStatus(module?.status),
      daily: typeof module?.daily === 'number' ? module!.daily : Number(module?.daily ?? 0),
      weekly: typeof module?.weekly === 'number' ? module!.weekly : Number(module?.weekly ?? 0),
    };
  }

  private normalizeTradeLocks(module?: Partial<RiskLimits['trade_locks']>): Required<RiskLimits['trade_locks']> {
    return {
      enabled: module?.enabled ?? false,
      status: this.normalizeStatus(module?.status),
      locks: Array.isArray(module?.locks)
        ? module!.locks.map((item) => ({
            venue: item.venue ?? '',
            node: item.node ?? '',
            locked: Boolean(item.locked),
            reason: item.reason ?? null,
          }))
        : [],
    };
  }

  private normalizeControls(module?: Partial<RiskLimits['controls']>): Required<RiskLimits['controls']> {
    const escalation: Partial<RiskEscalation> = (module?.escalation ?? {}) as Partial<RiskEscalation>;
    const warn = Number(escalation.warn_after ?? 1) || 1;
    const halt = Number(escalation.halt_after ?? Math.max(2, warn + 1)) || Math.max(2, warn + 1);
    const reset = Number(escalation.reset_minutes ?? 60) || 60;
    return {
      halt_on_breach: module?.halt_on_breach ?? true,
      notify_on_recovery: module?.notify_on_recovery ?? true,
      escalation: {
        warn_after: Math.max(1, warn),
        halt_after: Math.max(Math.max(1, warn), halt),
        reset_minutes: Math.max(1, reset),
      },
    };
  }

  private loadRiskSnapshot(): void {
    this.api.getRisk().subscribe({
      next: (response) => {
        const metrics = response?.risk;
        this.riskUsage.set(metrics?.exposure_limits ?? []);
        this.drawdownUsage.set(metrics?.drawdown_limits ?? []);
      },
      error: (err) => {
        console.error('Failed to load risk snapshot', err);
      },
    });
  }

  private syncPositionLimitEntries(module: Required<RiskLimits['position_limits']>): void {
    const array = this.positionLimitEntries;
    while (array.length > 0) {
      array.removeAt(0);
    }
    for (const entry of module.limits) {
      const group = this.createPositionLimitGroup(entry);
      if (!module.enabled) {
        group.disable({ emitEvent: false });
      }
      array.push(group);
    }
    if (array.length === 0) {
      const group = this.createPositionLimitGroup();
      if (!module.enabled) {
        group.disable({ emitEvent: false });
      }
      array.push(group);
    }
  }

  private syncTradeLockEntries(module: Required<RiskLimits['trade_locks']>): void {
    const array = this.tradeLockEntries;
    while (array.length > 0) {
      array.removeAt(0);
    }
    for (const entry of module.locks) {
      const group = this.createTradeLockGroup(entry);
      if (!module.enabled) {
        group.disable({ emitEvent: false });
      }
      array.push(group);
    }
    if (array.length === 0) {
      const group = this.createTradeLockGroup();
      if (!module.enabled) {
        group.disable({ emitEvent: false });
      }
      array.push(group);
    }
  }

  private createForm(): RiskFormGroup {
    return this.fb.nonNullable.group({
      positionLimits: this.fb.nonNullable.group({
        enabled: this.fb.nonNullable.control(false),
        status: this.fb.nonNullable.control<RiskModuleStatus>('stale', Validators.required),
        limits: this.fb.array<PositionLimitFormGroup>([]),
      }),
      maxLoss: this.fb.nonNullable.group(
        {
          enabled: this.fb.nonNullable.control(false),
          status: this.fb.nonNullable.control<RiskModuleStatus>('stale', Validators.required),
          daily: this.fb.nonNullable.control(0, [Validators.required, Validators.min(0)]),
          weekly: this.fb.nonNullable.control(0, [Validators.required, Validators.min(0)]),
        },
        { validators: RiskPage.maxLossRangeValidator },
      ),
      tradeLocks: this.fb.nonNullable.group({
        enabled: this.fb.nonNullable.control(false),
        status: this.fb.nonNullable.control<RiskModuleStatus>('stale', Validators.required),
        locks: this.fb.array<TradeLockFormGroup>([]),
      }),
      controls: this.fb.nonNullable.group({
        halt_on_breach: this.fb.nonNullable.control(true),
        notify_on_recovery: this.fb.nonNullable.control(true),
        escalation: this.fb.nonNullable.group({
          warn_after: this.fb.nonNullable.control(1, [Validators.required, Validators.min(1)]),
          halt_after: this.fb.nonNullable.control(2, [Validators.required, Validators.min(1)]),
          reset_minutes: this.fb.nonNullable.control(60, [Validators.required, Validators.min(1)]),
        }) as RiskEscalationFormGroup,
      }),
    }) as RiskFormGroup;
  }

  private createPositionLimitGroup(data?: Partial<PositionLimitConfig>): PositionLimitFormGroup {
    return this.fb.nonNullable.group({
      venue: this.fb.nonNullable.control(data?.venue ?? '', [Validators.required, Validators.maxLength(32)]),
      node: this.fb.nonNullable.control(data?.node ?? '', [Validators.required, Validators.maxLength(64)]),
      limit: this.fb.nonNullable.control(
        data?.limit ?? 0,
        [Validators.required, Validators.min(0)],
      ),
    });
  }

  private createTradeLockGroup(data?: Partial<TradeLockConfig>): TradeLockFormGroup {
    const group = this.fb.nonNullable.group({
      venue: this.fb.nonNullable.control(data?.venue ?? '', [Validators.required, Validators.maxLength(32)]),
      node: this.fb.nonNullable.control(data?.node ?? '', [Validators.required, Validators.maxLength(64)]),
      locked: this.fb.nonNullable.control(Boolean(data?.locked)),
      reason: this.fb.nonNullable.control(data?.reason ?? '', [Validators.maxLength(160)]),
    });
    group.addValidators(RiskPage.tradeLockReasonValidator);
    return group;
  }

  private setupModuleToggle(group: FormGroup, exclude: string[]): void {
    const enabledControl = group.get('enabled') as FormControl<boolean> | null;
    if (!enabledControl) {
      return;
    }
    this.applyModuleEnabledState(group, enabledControl.value ?? false, exclude);
    enabledControl.valueChanges
      .pipe(takeUntilDestroyed())
      .subscribe((enabled) => this.applyModuleEnabledState(group, !!enabled, exclude));
  }

  private applyModuleEnabledState(group: FormGroup, enabled: boolean, exclude: string[]): void {
    Object.entries(group.controls).forEach(([key, control]) => {
      if (exclude.includes(key)) {
        return;
      }
      if (enabled) {
        control.enable({ emitEvent: false });
      } else {
        control.disable({ emitEvent: false });
      }
    });
  }

  private markAllAsTouched(control: AbstractControl): void {
    control.markAsTouched();
    if (control instanceof FormGroup) {
      Object.values(control.controls).forEach((child) => this.markAllAsTouched(child));
    } else if (control instanceof FormArray) {
      control.controls.forEach((child) => this.markAllAsTouched(child));
    }
  }

  private normalizeStatus(value: string | null | undefined): RiskModuleStatus {
    if (RiskPage.allowedStatuses.includes(value as RiskModuleStatus)) {
      return value as RiskModuleStatus;
    }
    return 'stale';
  }

  private buildPayload(): RiskLimits {
    const raw = this.form.getRawValue();
    return {
      position_limits: {
        enabled: Boolean(raw.positionLimits?.enabled),
        status: this.normalizeStatus(raw.positionLimits?.status),
        limits: (raw.positionLimits?.limits ?? []).map((item) => ({
          venue: (item?.venue ?? '').trim().toUpperCase(),
          node: (item?.node ?? '').trim(),
          limit: Number(item?.limit ?? 0),
        })),
      },
      max_loss: {
        enabled: Boolean(raw.maxLoss?.enabled),
        status: this.normalizeStatus(raw.maxLoss?.status),
        daily: Number(raw.maxLoss?.daily ?? 0),
        weekly: Number(raw.maxLoss?.weekly ?? 0),
      },
      trade_locks: {
        enabled: Boolean(raw.tradeLocks?.enabled),
        status: this.normalizeStatus(raw.tradeLocks?.status),
        locks: (raw.tradeLocks?.locks ?? []).map((item) => {
          const reason = (item?.reason ?? '').trim();
          return {
            venue: (item?.venue ?? '').trim().toUpperCase(),
            node: (item?.node ?? '').trim(),
            locked: Boolean(item?.locked),
            reason: reason.length > 0 ? reason : null,
          };
        }),
      },
      controls: {
        halt_on_breach: Boolean(raw.controls?.halt_on_breach ?? true),
        notify_on_recovery: Boolean(raw.controls?.notify_on_recovery ?? true),
        escalation: {
          warn_after: Math.max(1, Number(raw.controls?.escalation?.warn_after ?? 1)),
          halt_after: Math.max(
            Math.max(1, Number(raw.controls?.escalation?.warn_after ?? 1)),
            Number(raw.controls?.escalation?.halt_after ?? 2),
          ),
          reset_minutes: Math.max(1, Number(raw.controls?.escalation?.reset_minutes ?? 60)),
        },
      },
    };
  }
}
