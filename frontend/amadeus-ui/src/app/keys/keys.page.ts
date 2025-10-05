import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  WritableSignal,
  inject,
  signal,
} from '@angular/core';
import {
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { KeysApi } from '../api/clients/keys.api';
import {
  ApiKey,
  KeyCreateRequest,
  KeyDeleteRequest,
  KeyScope,
  KeyUpdateRequest,
} from '../api/models';
import { NotificationService } from '../shared/notifications/notification.service';
import { encryptSecret, hashPassphrase } from './secret-crypto';

type KeyCreateFormGroup = FormGroup<{
  keyId: FormControl<string>;
  label: FormControl<string>;
  venue: FormControl<string>;
  apiKey: FormControl<string>;
  apiSecret: FormControl<string>;
  passphrase: FormControl<string>;
  passphraseHint: FormControl<string>;
  scopeTrade: FormControl<boolean>;
  scopeRead: FormControl<boolean>;
  scopeWithdraw: FormControl<boolean>;
  scopeCustom: FormControl<string>;
}>;

type KeyEditFormGroup = FormGroup<{
  keyId: FormControl<string>;
  label: FormControl<string>;
  venue: FormControl<string>;
  apiKey: FormControl<string>;
  apiSecret: FormControl<string>;
  rotateSecret: FormControl<boolean>;
  passphrase: FormControl<string>;
  passphraseHint: FormControl<string>;
  scopeTrade: FormControl<boolean>;
  scopeRead: FormControl<boolean>;
  scopeWithdraw: FormControl<boolean>;
  scopeCustom: FormControl<string>;
}>;

type KeyDeleteFormGroup = FormGroup<{
  confirmation: FormControl<string>;
  passphrase: FormControl<string>;
}>;

type KeyStatusTone = 'active' | 'stale' | 'idle';

interface KeyStatusDescriptor {
  label: string;
  description: string;
  tone: KeyStatusTone;
}

@Component({
  standalone: true,
  selector: 'app-keys-page',
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './keys.page.html',
  styleUrls: ['./keys.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KeysPage implements OnInit {
  private readonly keysApi = inject(KeysApi);
  private readonly fb = inject(FormBuilder);
  private readonly notifications = inject(NotificationService);

  readonly keys = signal<ApiKey[]>([]);
  readonly isLoading = signal(false);
  readonly isRefreshing = signal(false);
  readonly errorText = signal<string | null>(null);
  readonly lastUpdated = signal<Date | null>(null);

  readonly isCreateDialogOpen = signal(false);
  readonly isCreateSubmitting = signal(false);
  readonly createError = signal<string | null>(null);

  readonly isEditDialogOpen = signal(false);
  readonly isEditSubmitting = signal(false);
  readonly editError = signal<string | null>(null);
  readonly editDialogKey = signal<ApiKey | null>(null);

  readonly isDeleteDialogOpen = signal(false);
  readonly isDeleteSubmitting = signal(false);
  readonly deleteError = signal<string | null>(null);
  readonly deleteDialogKey = signal<ApiKey | null>(null);

  private readonly rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

  readonly createForm: KeyCreateFormGroup = this.createKeyForm();
  readonly editForm: KeyEditFormGroup = this.createEditForm();
  readonly deleteForm: KeyDeleteFormGroup = this.createDeleteForm();

  ngOnInit(): void {
    this.fetchKeys();
  }

  refresh(): void {
    this.fetchKeys({ silent: true });
  }

  openCreateDialog(): void {
    this.resetCreateForm();
    this.createError.set(null);
    this.isCreateDialogOpen.set(true);
  }

  closeCreateDialog(): void {
    this.isCreateDialogOpen.set(false);
    this.resetCreateForm();
  }

  openEditDialog(key: ApiKey): void {
    this.editDialogKey.set(key);
    this.resetEditForm(key);
    this.editError.set(null);
    this.isEditDialogOpen.set(true);
  }

  closeEditDialog(): void {
    this.isEditDialogOpen.set(false);
    this.editDialogKey.set(null);
    this.resetEditForm();
  }

  openDeleteDialog(key: ApiKey): void {
    this.deleteDialogKey.set(key);
    this.resetDeleteForm();
    this.deleteError.set(null);
    this.isDeleteDialogOpen.set(true);
  }

  closeDeleteDialog(): void {
    this.isDeleteDialogOpen.set(false);
    this.deleteDialogKey.set(null);
    this.resetDeleteForm();
  }

  trackByKeyId(_: number, item: ApiKey): string {
    return item.key_id;
  }

  maskSecret(key: ApiKey): string {
    if (key.fingerprint) {
      const suffix = key.fingerprint.slice(-4).padStart(4, '•');
      return `•••• ${suffix}`;
    }
    return '••••••••';
  }

  keyStatus(key: ApiKey): KeyStatusDescriptor {
    if (key.last_used_at) {
      const lastUsed = new Date(key.last_used_at);
      if (!Number.isNaN(lastUsed.getTime())) {
        const diffMs = Date.now() - lastUsed.getTime();
        const diffHours = diffMs / (1000 * 60 * 60);
        const description = `Last used ${this.formatRelativeTime(lastUsed)}`;
        if (diffHours <= 24) {
          return { label: 'Active', description, tone: 'active' };
        }
        if (diffHours <= 24 * 30) {
          return { label: 'Stale', description, tone: 'stale' };
        }
        return { label: 'Idle', description, tone: 'idle' };
      }
    }

    const created = new Date(key.created_at);
    const description = Number.isNaN(created.getTime())
      ? 'Never used'
      : `Provisioned ${this.formatRelativeTime(created)}`;
    return { label: 'Idle', description, tone: 'idle' };
  }

  async createKey(): Promise<void> {
    if (this.createForm.invalid) {
      this.createForm.markAllAsTouched();
      return;
    }

    const raw = this.createForm.getRawValue();
    const scopes = this.collectScopes(raw);
    if (scopes.length === 0) {
      this.createError.set('Select at least one scope.');
      return;
    }

    const keyId = raw.keyId.trim();
    const venue = raw.venue.trim();
    const apiKey = raw.apiKey.trim();
    const apiSecret = raw.apiSecret.trim();
    const passphrase = raw.passphrase.trim();

    if (!keyId || !venue || !apiKey || !apiSecret || !passphrase) {
      this.createError.set('Fill in all required fields.');
      return;
    }

    this.isCreateSubmitting.set(true);
    this.createError.set(null);

    try {
      const encryptedSecret = await encryptSecret(apiSecret, passphrase);
      const passphraseHash = await hashPassphrase(passphrase);
      const payload: KeyCreateRequest = {
        keyId,
        venue,
        apiKey,
        scopes,
        secret: encryptedSecret,
        passphraseHash,
      };

      const label = raw.label.trim();
      if (label) {
        payload.label = label;
      }

      const hint = raw.passphraseHint.trim();
      if (hint) {
        payload.passphraseHint = hint;
      }

      await firstValueFrom(this.keysApi.createKey(payload));
      this.notifications.success('API key created successfully.');
      this.closeCreateDialog();
      this.fetchKeys({ silent: true });
    } catch (error) {
      this.handleError(error, this.createError, 'Failed to create API key.');
    } finally {
      this.isCreateSubmitting.set(false);
    }
  }

  async updateKey(): Promise<void> {
    const key = this.editDialogKey();
    if (!key) {
      return;
    }

    if (this.editForm.invalid) {
      this.editForm.markAllAsTouched();
      return;
    }

    const raw = this.editForm.getRawValue();
    const scopes = this.collectScopes(raw);
    if (scopes.length === 0) {
      this.editError.set('Select at least one scope.');
      return;
    }

    const venue = raw.venue.trim();
    if (!venue) {
      this.editError.set('Venue is required.');
      return;
    }

    const passphrase = raw.passphrase.trim();
    if (!passphrase) {
      this.editError.set('Passphrase is required.');
      return;
    }

    if (raw.rotateSecret && !raw.apiSecret.trim()) {
      this.editError.set('Provide a new API secret to rotate credentials.');
      return;
    }

    this.isEditSubmitting.set(true);
    this.editError.set(null);

    try {
      const passphraseHash = await hashPassphrase(passphrase);
      const payload: KeyUpdateRequest = {
        label: raw.label.trim() || undefined,
        venue,
        scopes,
        passphraseHash,
      };

      const hint = raw.passphraseHint.trim();
      if (hint) {
        payload.passphraseHint = hint;
      }

      const newApiKey = raw.apiKey.trim();
      if (raw.rotateSecret) {
        const encryptedSecret = await encryptSecret(raw.apiSecret.trim(), passphrase);
        payload.secret = encryptedSecret;
        if (newApiKey) {
          payload.apiKey = newApiKey;
        }
      } else if (newApiKey) {
        payload.apiKey = newApiKey;
      }

      await firstValueFrom(this.keysApi.updateKey(key.key_id, payload));
      this.notifications.success('API key updated.');
      this.closeEditDialog();
      this.fetchKeys({ silent: true });
    } catch (error) {
      this.handleError(error, this.editError, 'Failed to update API key.');
    } finally {
      this.isEditSubmitting.set(false);
    }
  }

  async deleteKeyConfirmed(): Promise<void> {
    const key = this.deleteDialogKey();
    if (!key) {
      return;
    }

    if (this.deleteForm.invalid) {
      this.deleteForm.markAllAsTouched();
      return;
    }

    const raw = this.deleteForm.getRawValue();
    const confirmation = raw.confirmation.trim();
    if (confirmation !== key.key_id) {
      this.deleteError.set('Confirmation text does not match the key identifier.');
      return;
    }

    const passphrase = raw.passphrase.trim();
    if (!passphrase) {
      this.deleteError.set('Passphrase is required to delete credentials.');
      return;
    }

    this.isDeleteSubmitting.set(true);
    this.deleteError.set(null);

    try {
      const passphraseHash = await hashPassphrase(passphrase);
      const payload: KeyDeleteRequest = { passphraseHash };
      await firstValueFrom(this.keysApi.deleteKey(key.key_id, payload));
      this.notifications.success('API key deleted.');
      this.closeDeleteDialog();
      this.fetchKeys({ silent: true });
    } catch (error) {
      this.handleError(error, this.deleteError, 'Failed to delete API key.');
    } finally {
      this.isDeleteSubmitting.set(false);
    }
  }

  private fetchKeys(options?: { silent?: boolean }): void {
    if (options?.silent) {
      if (this.isRefreshing()) {
        return;
      }
      this.isRefreshing.set(true);
    } else {
      this.isLoading.set(true);
    }

    this.keysApi.listKeys().subscribe({
      next: (response) => {
        const sorted = [...response.keys].sort((a, b) => {
          const labelA = (a.label || a.key_id).toLowerCase();
          const labelB = (b.label || b.key_id).toLowerCase();
          return labelA.localeCompare(labelB);
        });
        this.keys.set(sorted);
        this.lastUpdated.set(new Date());
        this.errorText.set(null);
      },
      error: (err) => {
        console.error(err);
        const detail = (err as any)?.error?.detail;
        const message =
          typeof detail === 'string' && detail.trim().length > 0
            ? detail
            : 'Unable to load API keys.';
        this.errorText.set(message);
        if (options?.silent) {
          this.isRefreshing.set(false);
        } else {
          this.isLoading.set(false);
        }
      },
      complete: () => {
        if (options?.silent) {
          this.isRefreshing.set(false);
        } else {
          this.isLoading.set(false);
        }
      },
    });
  }

  private collectScopes(raw: {
    scopeRead: boolean;
    scopeTrade: boolean;
    scopeWithdraw: boolean;
    scopeCustom: string;
  }): KeyScope[] {
    const scopes = new Set<KeyScope>();
    if (raw.scopeRead) {
      scopes.add('read');
    }
    if (raw.scopeTrade) {
      scopes.add('trade');
    }
    if (raw.scopeWithdraw) {
      scopes.add('withdraw');
    }
    const customScopes = raw.scopeCustom
      .split(',')
      .map((scope) => scope.trim())
      .filter((scope) => scope.length > 0);
    for (const scope of customScopes) {
      const normalized = scope.toLowerCase() as KeyScope;
      scopes.add(normalized);
    }
    return Array.from(scopes);
  }

  private createKeyForm(): KeyCreateFormGroup {
    return this.fb.group({
      keyId: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      label: this.fb.nonNullable.control(''),
      venue: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      apiKey: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      apiSecret: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      passphrase: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.minLength(8)],
      }),
      passphraseHint: this.fb.nonNullable.control(''),
      scopeTrade: this.fb.nonNullable.control(true),
      scopeRead: this.fb.nonNullable.control(true),
      scopeWithdraw: this.fb.nonNullable.control(false),
      scopeCustom: this.fb.nonNullable.control(''),
    });
  }

  private resetCreateForm(): void {
    this.createForm.reset({
      keyId: '',
      label: '',
      venue: '',
      apiKey: '',
      apiSecret: '',
      passphrase: '',
      passphraseHint: '',
      scopeTrade: true,
      scopeRead: true,
      scopeWithdraw: false,
      scopeCustom: '',
    });
    this.createForm.markAsPristine();
    this.createForm.markAsUntouched();
  }

  private createEditForm(): KeyEditFormGroup {
    return this.fb.group({
      keyId: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      label: this.fb.nonNullable.control(''),
      venue: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      apiKey: this.fb.nonNullable.control(''),
      apiSecret: this.fb.nonNullable.control(''),
      rotateSecret: this.fb.nonNullable.control(false),
      passphrase: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.minLength(8)],
      }),
      passphraseHint: this.fb.nonNullable.control(''),
      scopeTrade: this.fb.nonNullable.control(true),
      scopeRead: this.fb.nonNullable.control(true),
      scopeWithdraw: this.fb.nonNullable.control(false),
      scopeCustom: this.fb.nonNullable.control(''),
    });
  }

  private resetEditForm(key?: ApiKey): void {
    if (!key) {
      this.editForm.reset({
        keyId: '',
        label: '',
        venue: '',
        apiKey: '',
        apiSecret: '',
        rotateSecret: false,
        passphrase: '',
        passphraseHint: '',
        scopeTrade: true,
        scopeRead: true,
        scopeWithdraw: false,
        scopeCustom: '',
      });
      this.editForm.markAsPristine();
      this.editForm.markAsUntouched();
      return;
    }

    const defaultScopes = new Set<KeyScope>(['read', 'trade', 'withdraw']);
    const customScopes = (key.scopes || []).filter((scope) => !defaultScopes.has(scope as KeyScope));

    this.editForm.reset({
      keyId: key.key_id,
      label: key.label ?? '',
      venue: key.venue,
      apiKey: '',
      apiSecret: '',
      rotateSecret: false,
      passphrase: '',
      passphraseHint: key.passphrase_hint ?? '',
      scopeTrade: key.scopes?.includes('trade') ?? false,
      scopeRead: key.scopes?.includes('read') ?? false,
      scopeWithdraw: key.scopes?.includes('withdraw') ?? false,
      scopeCustom: customScopes.join(', '),
    });

    this.editForm.markAsPristine();
    this.editForm.markAsUntouched();
  }

  private createDeleteForm(): KeyDeleteFormGroup {
    return this.fb.group({
      confirmation: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      passphrase: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.minLength(8)],
      }),
    });
  }

  private resetDeleteForm(): void {
    this.deleteForm.reset({
      confirmation: '',
      passphrase: '',
    });
    this.deleteForm.markAsPristine();
    this.deleteForm.markAsUntouched();
  }

  private formatRelativeTime(date: Date): string {
    const divisions: Array<[Intl.RelativeTimeFormatUnit, number]> = [
      ['year', 1000 * 60 * 60 * 24 * 365],
      ['month', 1000 * 60 * 60 * 24 * 30],
      ['week', 1000 * 60 * 60 * 24 * 7],
      ['day', 1000 * 60 * 60 * 24],
      ['hour', 1000 * 60 * 60],
      ['minute', 1000 * 60],
    ];
    const diff = date.getTime() - Date.now();
    for (const [unit, ms] of divisions) {
      if (Math.abs(diff) >= ms || unit === 'minute') {
        const value = diff / ms;
        return this.rtf.format(Math.round(value), unit);
      }
    }
    return this.rtf.format(0, 'minute');
  }

  private handleError(
    error: unknown,
    target: WritableSignal<string | null>,
    fallback: string,
  ): void {
    console.error(error);
    const detail = (error as any)?.error?.detail ?? (error as any)?.message;
    const message =
      typeof detail === 'string' && detail.trim().length > 0 ? (detail as string) : fallback;
    target.set(message);
    this.notifications.error(message);
  }
}
