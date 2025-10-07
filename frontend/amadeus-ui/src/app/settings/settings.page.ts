import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  WritableSignal,
  computed,
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
import { MarketApi } from '../api/clients/market.api';
import { NodesApi } from '../api/clients/nodes.api';
import { UsersApi } from '../api/clients/users.api';
import { IntegrationsApi } from '../api/clients/integrations.api';
import {
  ApiKey,
  KeyCreateRequest,
  KeyDeleteRequest,
  KeyScope,
  KeyUpdateRequest,
  NodeDetailResponse,
  NodeMode,
  ExchangeDescriptor,
  UserProfile,
  AccountUpdateRequest,
  PasswordUpdateRequest,
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

type AccountFormGroup = FormGroup<{
  name: FormControl<string>;
  email: FormControl<string>;
  username: FormControl<string>;
  currentPassword: FormControl<string>;
  password: FormControl<string>;
  confirmPassword: FormControl<string>;
}>;

type KeyStatusTone = 'active' | 'stale' | 'idle' | 'expiring' | 'expired';

interface KeyStatusDescriptor {
  label: string;
  description: string;
  tone: KeyStatusTone;
}

type AdapterEnvironment = 'live' | 'historical' | 'simulation';

interface AdapterContext {
  alias: string;
  label: string;
  selectionKey: string;
  required: boolean;
  venue: string | null;
  environment: AdapterEnvironment;
  mode: string;
  assignedKeyId?: string;
}

interface AdapterOption {
  key: ApiKey;
  compatible: boolean;
}

interface AdapterView extends AdapterContext {
  options: AdapterOption[];
  warnings: string[];
}

interface NodeAssignmentContext {
  nodeId: string;
  nodeMode: NodeMode;
  strategyName: string;
  adapters: AdapterContext[];
}

interface NodeAssignmentView extends NodeAssignmentContext {
  adapters: AdapterView[];
  hasWarnings: boolean;
}

@Component({
  standalone: true,
  selector: 'app-settings-page',
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './settings.page.html',
  styleUrls: ['./settings.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsPage implements OnInit {
  private readonly keysApi = inject(KeysApi);
  private readonly nodesApi = inject(NodesApi);
  private readonly marketApi = inject(MarketApi);
  private readonly usersApi = inject(UsersApi);
  private readonly integrationsApi = inject(IntegrationsApi);
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

  readonly assignmentPanels = signal<NodeAssignmentContext[]>([]);
  readonly assignmentSelections = signal<Record<string, string | null>>({});
  readonly knownVenues = signal<string[]>([]);
  readonly isAssignmentsLoading = signal(false);
  readonly assignmentsError = signal<string | null>(null);
  readonly assignmentsView = computed<NodeAssignmentView[]>(() => this.computeAssignmentView());

  readonly availableExchanges = signal<ExchangeDescriptor[]>([]);
  readonly isExchangesLoading = signal(false);
  readonly exchangesError = signal<string | null>(null);

  readonly activeUser = signal<UserProfile | null>(null);
  readonly isAccountSaving = signal(false);
  readonly accountError = signal<string | null>(null);
  readonly accountSuccess = signal<string | null>(null);

  readonly accountForm: AccountFormGroup = this.createAccountForm();
  
  private readonly healthAlertsDisplayed = new Set<string>();

  private readonly rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

  readonly createForm: KeyCreateFormGroup = this.createKeyForm();
  readonly editForm: KeyEditFormGroup = this.createEditForm();
  readonly deleteForm: KeyDeleteFormGroup = this.createDeleteForm();
  readonly isCreateCustomVenue = signal(false);
  readonly isEditCustomVenue = signal(false);
  readonly venueOptions = computed<ExchangeDescriptor[]>(() => this.computeVenueOptions());

  ngOnInit(): void {
    this.fetchKeys();
    void this.loadAssignmentContext();
    this.loadExchangeCatalog();
    this.loadAccountProfile();
  }

  refresh(): void {
    this.fetchKeys({ silent: true });
  }

  private loadExchangeCatalog(): void {
    this.isExchangesLoading.set(true);
    this.exchangesError.set(null);
    this.integrationsApi.listExchanges().subscribe({
      next: (response) => {
        const sanitized = (response.exchanges ?? [])
          .map((exchange) => ({
            code: (exchange.code || '').toUpperCase(),
            name: exchange.name || exchange.code || '',
          }))
          .filter((exchange) => exchange.code.length > 0);
        sanitized.sort((a, b) => a.name.localeCompare(b.name));
        this.availableExchanges.set(sanitized);
        this.isExchangesLoading.set(false);
      },
      error: (error) => {
        console.error(error);
        this.exchangesError.set('Unable to load exchange catalog.');
        this.isExchangesLoading.set(false);
      },
    });
  }

  private loadAccountProfile(): void {
    this.accountError.set(null);
    this.accountSuccess.set(null);
    this.usersApi.getAccount().subscribe({
      next: (response) => {
        const account = response.account ?? null;
        this.activeUser.set(account);
        if (account) {
          this.accountForm.reset({
            name: account.name ?? '',
            email: account.email ?? '',
            username: account.username ?? '',
            currentPassword: '',
            password: '',
            confirmPassword: '',
          });
        } else {
          this.accountForm.reset({
            name: '',
            email: '',
            username: '',
            currentPassword: '',
            password: '',
            confirmPassword: '',
          });
        }
        this.accountForm.markAsPristine();
        this.accountForm.markAsUntouched();
      },
      error: (error) => {
        this.handleError(error, this.accountError, 'Unable to load account profile.');
      },
    });
  }

  openCreateDialog(): void {
    this.resetCreateForm();
    this.createError.set(null);
    this.isCreateCustomVenue.set(false);
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
    this.isEditCustomVenue.set(!this.hasKnownVenue(key.venue));
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
    if (key.api_key_masked) {
      return key.api_key_masked;
    }
    if (key.fingerprint) {
      const suffix = key.fingerprint.slice(-4).padStart(4, '•');
      return `•••• ${suffix}`;
    }
    return '••••••••';
  }

  reloadAssignments(): void {
    void this.loadAssignmentContext();
  }

  onAssignmentChange(selectionKey: string, keyId: string): void {
    const normalized = keyId && keyId.trim().length > 0 ? keyId : null;
    this.assignmentSelections.update((current) => ({ ...current, [selectionKey]: normalized }));

    const adapter = this
      .assignmentsView()
      .flatMap((node) => node.adapters ?? [])
      .find((item) => item.selectionKey === selectionKey);

    if (!adapter) {
      return;
    }

    if (normalized) {
      const option = adapter.options.find((opt) => opt.key.key_id === normalized);
      const keyLabel = option?.key.label || option?.key.key_id || normalized;
      this.notifications.success(`Assigned ${keyLabel} to ${adapter.label}.`, 'Key assignments');
    } else {
      this.notifications.info(`Cleared credential assignment for ${adapter.label}.`, 'Key assignments');
    }
  }

  onCreateVenueSelected(value: string): void {
    if (value === '__custom__') {
      this.isCreateCustomVenue.set(true);
      this.createForm.controls.venue.setValue('');
    } else {
      this.isCreateCustomVenue.set(false);
      this.createForm.controls.venue.setValue(value);
    }
  }

  onEditVenueSelected(value: string): void {
    if (value === '__custom__') {
      this.isEditCustomVenue.set(true);
      this.editForm.controls.venue.setValue('');
    } else {
      this.isEditCustomVenue.set(false);
      this.editForm.controls.venue.setValue(value);
    }
  }

  async saveAccountSettings(): Promise<void> {
    this.accountError.set(null);
    this.accountSuccess.set(null);

    const currentUser = this.activeUser();
    if (!currentUser) {
      this.accountError.set('No user profile available.');
      return;
    }

    if (this.accountForm.invalid) {
      this.accountForm.markAllAsTouched();
      return;
    }

    const raw = this.accountForm.getRawValue();
    const currentPassword = raw.currentPassword.trim();
    const newPassword = raw.password.trim();
    const confirmPassword = raw.confirmPassword.trim();

    const wantsPasswordChange =
      currentPassword.length > 0 || newPassword.length > 0 || confirmPassword.length > 0;

    if (wantsPasswordChange) {
      if (!currentPassword) {
        this.accountError.set('Current password is required to update your password.');
        return;
      }
      if (!newPassword) {
        this.accountError.set('New password must be provided.');
        return;
      }
      if (newPassword.length < 8) {
        this.accountError.set('Password must be at least 8 characters.');
        return;
      }
      if (newPassword !== confirmPassword) {
        this.accountError.set('Password confirmation does not match.');
        return;
      }
    }

    const accountPayload: AccountUpdateRequest = {};
    const name = raw.name.trim();
    if (name && name !== currentUser.name) {
      accountPayload.name = name;
    }

    const email = raw.email.trim();
    if (email && email !== currentUser.email) {
      accountPayload.email = email;
    }

    const username = raw.username.trim();
    if (username && username !== currentUser.username) {
      accountPayload.username = username;
    }

    const operations: Array<'account' | 'password'> = [];
    if (Object.keys(accountPayload).length > 0) {
      operations.push('account');
    }
    if (wantsPasswordChange && newPassword) {
      operations.push('password');
    }

    if (operations.length === 0) {
      this.accountSuccess.set('Account settings are already up to date.');
      return;
    }

    this.isAccountSaving.set(true);
    try {
      let latestAccount = currentUser;

      if (operations.includes('account')) {
        const accountResponse = await firstValueFrom(this.usersApi.updateAccount(accountPayload));
        latestAccount = accountResponse.account;
        this.activeUser.set(latestAccount);
      }

      if (operations.includes('password')) {
        const passwordPayload: PasswordUpdateRequest = {
          currentPassword,
          newPassword,
        };
        const passwordResponse = await firstValueFrom(this.usersApi.updatePassword(passwordPayload));
        latestAccount = passwordResponse.account;
        this.activeUser.set(latestAccount);
      }

      this.accountForm.reset({
        name: latestAccount.name ?? '',
        email: latestAccount.email ?? '',
        username: latestAccount.username ?? '',
        currentPassword: '',
        password: '',
        confirmPassword: '',
      });
      this.accountForm.markAsPristine();
      this.accountForm.markAsUntouched();

      const successMessage =
        operations.length === 2
          ? 'Account details and password updated successfully.'
          : operations[0] === 'password'
            ? 'Password updated successfully.'
            : 'Account settings updated successfully.';
      this.accountSuccess.set(successMessage);

      const notificationMessage =
        operations.length === 2
          ? 'Account and password updated.'
          : operations[0] === 'password'
            ? 'Password updated.'
            : 'Account settings updated.';
      this.notifications.success(notificationMessage, 'Settings');
    } catch (error) {
      this.handleError(error, this.accountError, 'Failed to update account settings.');
    } finally {
      this.isAccountSaving.set(false);
    }
  }

  adapterOptionLabel(option: AdapterOption): string {
    const label = option.key.label || option.key.key_id;
    const venue = option.key.venue ? ` (${option.key.venue})` : '';
    const compatibility = option.compatible ? '' : ' — incompatible';
    return `${label}${venue}${compatibility}`;
  }

  formatEnvironment(environment: AdapterEnvironment): string {
    switch (environment) {
      case 'historical':
        return 'Historical';
      case 'simulation':
        return 'Simulation';
      default:
        return 'Live';
    }
  }

  formatMode(mode: string): string {
    if (!mode) {
      return '—';
    }
    const lower = mode.toLowerCase();
    return lower.charAt(0).toUpperCase() + lower.slice(1);
  }

  formatVenue(venue: string | null): string {
    return venue ?? 'Unknown';
  }

  keyStatus(key: ApiKey): KeyStatusDescriptor {
    const now = Date.now();
    if (key.expires_at) {
      const expiresAt = new Date(key.expires_at);
      if (!Number.isNaN(expiresAt.getTime())) {
        const diffMs = expiresAt.getTime() - now;
        const description = diffMs >= 0
          ? `Expires ${this.formatRelativeTime(expiresAt)}`
          : `Expired ${this.formatRelativeTime(expiresAt)}`;
        if (diffMs <= 0) {
          return { label: 'Expired', description, tone: 'expired' };
        }
        const sevenDays = 1000 * 60 * 60 * 24 * 7;
        if (diffMs <= sevenDays) {
          return { label: 'Expiring', description, tone: 'expiring' };
        }
      }
    }

    if (key.last_used_at) {
      const lastUsed = new Date(key.last_used_at);
      if (!Number.isNaN(lastUsed.getTime())) {
        const diffMs = now - lastUsed.getTime();
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

  private computeAssignmentView(): NodeAssignmentView[] {
    const contexts = this.assignmentPanels();
    if (contexts.length === 0) {
      return [];
    }

    const keys = this.keys();
    const selections = this.assignmentSelections();
    const knownVenues = new Set(this.knownVenues());

    return contexts.map((context) => {
      const adapters = context.adapters.map<AdapterView>((adapter) => {
        const selected =
          selections.hasOwnProperty(adapter.selectionKey)
            ? selections[adapter.selectionKey]
            : adapter.assignedKeyId ?? null;
        const compatibleKeys = this.filterCompatibleKeys(keys, adapter);
        const options: AdapterOption[] = compatibleKeys.map((key) => ({ key, compatible: true }));

        if (selected) {
          const selectedKey = keys.find((key) => key.key_id === selected);
          if (selectedKey) {
            if (!options.some((option) => option.key.key_id === selectedKey.key_id)) {
              options.unshift({ key: selectedKey, compatible: false });
            }
          } else {
            options.unshift({ key: this.createPlaceholderKey(selected), compatible: false });
          }
        }

        const warnings = this.collectAdapterWarnings(
          adapter,
          selected,
          keys,
          context.nodeMode,
          knownVenues,
          options,
        );

        return {
          ...adapter,
          assignedKeyId: selected ?? undefined,
          options,
          warnings,
        };
      });

      return {
        ...context,
        adapters,
        hasWarnings: adapters.some((adapter) => adapter.warnings.length > 0),
      };
    });
  }

  private sortKeys(keys: ApiKey[]): ApiKey[] {
    return [...keys].sort((a, b) => {
      const aLabel = (a.label || a.key_id).toLowerCase();
      const bLabel = (b.label || b.key_id).toLowerCase();
      return aLabel.localeCompare(bLabel);
    });
  }

  private filterCompatibleKeys(keys: ApiKey[], adapter: AdapterContext): ApiKey[] {
    return this.sortKeys(keys.filter((key) => this.isKeyCompatibleWithAdapter(key, adapter)));
  }

  private isKeyCompatibleWithAdapter(key: ApiKey, adapter: AdapterContext): boolean {
    if (adapter.venue) {
      const keyVenue = (key.venue || '').toUpperCase();
      if (keyVenue !== adapter.venue) {
        return false;
      }
    }

    const scopes = new Set(key.scopes || []);
    const mode = adapter.mode.toLowerCase();
    if (mode === 'write') {
      return scopes.has('trade');
    }
    return scopes.has('read') || scopes.has('trade');
  }

  private collectAdapterWarnings(
    adapter: AdapterContext,
    selectedKeyId: string | null,
    keys: ApiKey[],
    nodeMode: NodeMode,
    knownVenues: Set<string>,
    options: AdapterOption[],
  ): string[] {
    const warnings = new Set<string>();
    const nodeModeNormalized = (nodeMode || '').toLowerCase();

    if (adapter.environment === 'live' && nodeModeNormalized !== 'live') {
      warnings.add('Live adapter configured on non-live node.');
    }
    if (adapter.environment === 'historical' && nodeModeNormalized === 'live') {
      warnings.add('Historical adapter configured on a live node.');
    }

    if (!adapter.venue) {
      warnings.add('Adapter venue could not be determined from node or market services.');
    } else if (knownVenues.size > 0 && !knownVenues.has(adapter.venue)) {
      warnings.add(`Adapter venue ${adapter.venue} is not registered in the market service.`);
    }

    const compatibleOptions = options.filter((option) => option.compatible).length;
    if (compatibleOptions === 0) {
      warnings.add('No compatible keys available for this adapter.');
    }

    const selectedKey = selectedKeyId ? keys.find((key) => key.key_id === selectedKeyId) : undefined;
    if (selectedKeyId && !selectedKey) {
      warnings.add('Assigned key is no longer provisioned.');
    }

    if (selectedKey) {
      const keyVenue = (selectedKey.venue || '').toUpperCase();
      if (adapter.venue && keyVenue !== adapter.venue) {
        warnings.add(`Assigned key venue ${selectedKey.venue} does not match ${adapter.venue}.`);
      }
      const scopes = new Set(selectedKey.scopes || []);
      const mode = adapter.mode.toLowerCase();
      if (mode === 'write' && !scopes.has('trade')) {
        warnings.add('Assigned key is missing the trade scope required for execution adapters.');
      }
      if (mode !== 'write' && !scopes.has('read')) {
        warnings.add('Assigned key is missing the read scope required for data adapters.');
      }
    } else if (adapter.required) {
      warnings.add('This adapter requires a credential assignment.');
    }

    return Array.from(warnings);
  }

  private async loadAssignmentContext(): Promise<void> {
    this.isAssignmentsLoading.set(true);
    this.assignmentsError.set(null);

    try {
      const [nodesResponse, instrumentsResponse] = await Promise.all([
        firstValueFrom(this.nodesApi.listNodes()),
        firstValueFrom(this.marketApi.listInstruments()),
      ]);

      const venueSet = new Set<string>();
      instrumentsResponse.instruments.forEach((instrument) => {
        if (instrument.venue) {
          venueSet.add(instrument.venue.toUpperCase());
        }
      });
      this.knownVenues.set(Array.from(venueSet));

      const nodes = nodesResponse.nodes ?? [];
      const details = await Promise.all(
        nodes.map((node) =>
          firstValueFrom(this.nodesApi.getNodeDetail(node.id)).catch((error) => {
            console.error(error);
            return null;
          }),
        ),
      );

      const contexts: NodeAssignmentContext[] = [];
      const selections: Record<string, string | null> = {};

      for (const detail of details) {
        if (!detail) {
          continue;
        }
        const context = this.buildNodeAssignmentContext(detail, venueSet);
        contexts.push(context);
        context.adapters.forEach((adapter) => {
          selections[adapter.selectionKey] = adapter.assignedKeyId ?? null;
        });
      }

      this.assignmentPanels.set(contexts);
      this.assignmentSelections.set(selections);
    } catch (error) {
      console.error(error);
      this.assignmentsError.set('Unable to load node assignment context.');
    } finally {
      this.isAssignmentsLoading.set(false);
    }
  }

  private buildNodeAssignmentContext(
    detail: NodeDetailResponse,
    knownVenues: Set<string>,
  ): NodeAssignmentContext {
    const nodeMode = detail.node.mode ?? 'live';
    const strategy = detail.config.strategy;
    const strategyName = strategy?.name || strategy?.id || 'Unnamed strategy';
    const dataSources = detail.config.dataSources ?? [];
    const keyReferences = detail.config.keyReferences ?? [];
    const adapters: AdapterContext[] = [];

    const dataSourceMeta = dataSources.map((source, index) => {
      const venueToken = this.extractVenueToken(source.label) ?? this.extractVenueToken(source.id);
      return {
        source,
        id: source.id || `data-source-${index}`,
        label: source.label || source.id || `Adapter ${index + 1}`,
        venue: this.normalizeVenue(venueToken),
        environment: this.deriveEnvironment(nodeMode, source.type),
        mode: (source.mode || '').toLowerCase() || 'read',
      };
    });

    if (keyReferences.length > 0) {
      keyReferences.forEach((reference, index) => {
        const alias = reference.alias || `Credential ${index + 1}`;
        const selectionKey = `${detail.node.id}::${alias.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${index}`;
        const matchedSource = dataSourceMeta.find((meta) =>
          this.isAliasMatch(meta.label, alias) || this.isAliasMatch(meta.id, alias),
        );

        const venueToken =
          matchedSource?.venue ??
          this.normalizeVenue(this.extractVenueToken(alias) ?? this.extractVenueToken(reference.keyId));

        adapters.push({
          alias,
          label: matchedSource?.label ?? alias,
          selectionKey,
          required: reference.required ?? false,
          venue: venueToken,
          environment: matchedSource?.environment ?? this.deriveEnvironment(nodeMode, undefined),
          mode: matchedSource?.mode ?? (reference.required ? 'write' : 'read'),
          assignedKeyId: reference.keyId,
        });
      });
    } else if (dataSourceMeta.length > 0) {
      dataSourceMeta.forEach((meta, index) => {
        const selectionKey = `${detail.node.id}::${meta.id || index}`;
        adapters.push({
          alias: meta.label,
          label: meta.label,
          selectionKey,
          required: meta.mode === 'write',
          venue: meta.venue,
          environment: meta.environment,
          mode: meta.mode,
        });
      });
    }

    return {
      nodeId: detail.node.id,
      nodeMode,
      strategyName,
      adapters,
    };
  }

  private deriveEnvironment(nodeMode: NodeMode, sourceType?: string | null): AdapterEnvironment {
    const type = (sourceType || '').toLowerCase();
    if (type.includes('live')) {
      return 'live';
    }
    if (type.includes('hist') || type.includes('backtest')) {
      return 'historical';
    }

    const normalizedMode = (nodeMode || '').toLowerCase();
    if (normalizedMode === 'live') {
      return 'live';
    }
    if (normalizedMode === 'backtest') {
      return 'historical';
    }
    return 'simulation';
  }

  private extractVenueToken(value?: string | null): string | null {
    if (!value) {
      return null;
    }
    const match = value.match(/[a-zA-Z]{2,}/);
    return match ? match[0].toUpperCase() : null;
  }

  private normalizeVenue(token: string | null): string | null {
    if (!token) {
      return null;
    }
    const normalized = token.replace(/[^a-z0-9]/gi, '').toUpperCase();
    return normalized.length > 0 ? normalized : null;
  }

  private isAliasMatch(source?: string | null, target?: string | null): boolean {
    if (!source || !target) {
      return false;
    }
    const normalSource = source.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    const normalTarget = target.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    if (!normalSource || !normalTarget) {
      return false;
    }
    const tokens = normalSource.split(' ').filter(Boolean);
    return tokens.some((token) => normalTarget.includes(token));
  }

  private createPlaceholderKey(keyId: string): ApiKey {
    return {
      key_id: keyId,
      venue: 'UNKNOWN',
      scopes: [],
      created_at: new Date(0).toISOString(),
    };
  }

  private evaluateKeyHealth(keys: ApiKey[]): void {
    const now = Date.now();
    const expiringThreshold = 1000 * 60 * 60 * 24 * 7;
    const unusedThreshold = 1000 * 60 * 60 * 24 * 30;

    for (const key of keys) {
      if (key.expires_at) {
        const expiresAt = new Date(key.expires_at);
        if (!Number.isNaN(expiresAt.getTime()) && expiresAt.getTime() - now <= expiringThreshold) {
          const id = `${key.key_id}-expiring`;
          if (!this.healthAlertsDisplayed.has(id)) {
            const message = `${key.label || key.key_id} expires ${this.formatRelativeTime(expiresAt)}.`;
            this.notifications.warning(message, 'Key health', 10000);
            this.healthAlertsDisplayed.add(id);
          }
        }
      }

      const lastUsed = key.last_used_at ? new Date(key.last_used_at) : null;
      const createdAt = new Date(key.created_at);
      const isNewKey = !Number.isNaN(createdAt.getTime()) && now - createdAt.getTime() < 1000 * 60 * 60 * 48;
      const isStale =
        !lastUsed || Number.isNaN(lastUsed.getTime()) || now - lastUsed.getTime() > unusedThreshold;

      if (!isNewKey && isStale) {
        const id = `${key.key_id}-unused`;
        if (!this.healthAlertsDisplayed.has(id)) {
          const label = key.label || key.key_id;
          const message = lastUsed
            ? `${label} was last used ${this.formatRelativeTime(lastUsed)}.`
            : `${label} has not been used yet.`;
          this.notifications.warning(message, 'Key health', 10000);
          this.healthAlertsDisplayed.add(id);
        }
      }
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
        this.evaluateKeyHealth(sorted);
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

  private createAccountForm(): AccountFormGroup {
    return this.fb.group({
      name: this.fb.nonNullable.control('', { validators: [Validators.required] }),
      email: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.email],
      }),
      username: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.minLength(3)],
      }),
      currentPassword: this.fb.nonNullable.control(''),
      password: this.fb.nonNullable.control(''),
      confirmPassword: this.fb.nonNullable.control(''),
    });
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
    this.isCreateCustomVenue.set(false);
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
      this.isEditCustomVenue.set(false);
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
    this.isEditCustomVenue.set(!this.hasKnownVenue(key.venue));
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

  private computeVenueOptions(): ExchangeDescriptor[] {
    const map = new Map<string, string>();

    for (const exchange of this.availableExchanges()) {
      const code = (exchange.code || '').toUpperCase();
      if (code.length === 0) {
        continue;
      }
      map.set(code, exchange.name || code);
    }

    for (const venue of this.knownVenues()) {
      const code = (venue || '').toUpperCase();
      if (code.length === 0 || map.has(code)) {
        continue;
      }
      map.set(code, code);
    }

    for (const key of this.keys()) {
      const code = (key.venue || '').toUpperCase();
      if (code.length === 0 || map.has(code)) {
        continue;
      }
      map.set(code, key.venue || code);
    }

    return Array.from(map.entries())
      .map(([code, name]) => ({ code, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  private hasKnownVenue(venue: string | null | undefined): boolean {
    if (!venue) {
      return false;
    }
    const code = venue.toUpperCase();
    return this.venueOptions().some((option) => option.code === code);
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
