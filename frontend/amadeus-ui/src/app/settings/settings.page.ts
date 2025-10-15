import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
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
  AbstractControl,
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { toDataURL } from 'qrcode';
import { AuthApi } from '../api/clients/auth.api';
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
  AuthUser,
  PasswordUpdateRequest,
  MfaBackupCodesRequest,
} from '../api/models';
import { NotificationService } from '../shared/notifications/notification.service';
import { encryptSecret, hashPassphrase } from './secret-crypto';
import { AuthStateService } from '../shared/auth/auth-state.service';

type KeyCreateFormGroup = FormGroup<{
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

type EmailFormGroup = FormGroup<{
  email: FormControl<string>;
  password: FormControl<string>;
}>;

type PasswordFormGroup = FormGroup<{
  currentPassword: FormControl<string>;
  password: FormControl<string>;
  confirmPassword: FormControl<string>;
}>; 

type TwoFactorFormGroup = FormGroup<{
  code: FormControl<string>;
}>;

type PasswordConfirmFormGroup = FormGroup<{
  password: FormControl<string>;
}>;

type BackupCodesFormGroup = FormGroup<{
  code: FormControl<string>;
  password: FormControl<string>;
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
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './settings.page.html',
  styleUrls: ['./settings.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsPage implements OnInit {
  private readonly authApi = inject(AuthApi);
  private readonly keysApi = inject(KeysApi);
  private readonly nodesApi = inject(NodesApi);
  private readonly marketApi = inject(MarketApi);
  private readonly usersApi = inject(UsersApi);
  private readonly integrationsApi = inject(IntegrationsApi);
  private readonly fb = inject(FormBuilder);
  private readonly notifications = inject(NotificationService);
  private readonly authState = inject(AuthStateService);

  readonly keys = signal<ApiKey[]>([]);
  readonly isLoading = signal(false);
  readonly isRefreshing = signal(false);
  readonly errorText = signal<string | null>(null);
  readonly lastUpdated = signal<Date | null>(null);

  readonly activeTab = signal<'account' | 'security' | 'api-keys'>('account');

  readonly isCreateDialogOpen = signal(false);
  readonly isCreateSubmitting = signal(false);
  readonly createError = signal<string | null>(null);
  readonly isCreateAdvancedOpen = signal(false);

  readonly isEditDialogOpen = signal(false);
  readonly isEditSubmitting = signal(false);
  readonly editError = signal<string | null>(null);
  readonly editDialogKey = signal<ApiKey | null>(null);
  readonly isEditAdvancedOpen = signal(false);

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
  readonly authUser = signal<AuthUser | null>(null);
  readonly user = computed(() => this.authState.currentUser());
  readonly isEmailDialogOpen = signal(false);
  readonly isPasswordDialogOpen = signal(false);

  readonly isLogoutDialogOpen = signal(false);
  readonly isLogoutSubmitting = signal(false);
  readonly logoutError = signal<string | null>(null);

  readonly isTwoFactorEnabled = signal(false);
  readonly isTwoFactorLoading = signal(false);
  readonly twoFactorError = signal<string | null>(null);
  readonly twoFactorSetupError = signal<string | null>(null);
  readonly isTwoFactorSubmitting = signal(false);
  readonly twoFactorSecret = signal<string | null>(null);
  readonly twoFactorQr = signal<string | null>(null);
  readonly twoFactorBackupCodes = signal<string[]>([]);
  readonly twoFactorBackupCodesError = signal<string | null>(null);
  readonly twoFactorBackupCodesSuccess = signal<string | null>(null);
  readonly isBackupCodesLoading = signal(false);
  readonly isDisableTwoFactorDialogOpen = signal(false);
  readonly isDisableTwoFactorSubmitting = signal(false);
  readonly disableTwoFactorError = signal<string | null>(null);

  readonly emailForm: EmailFormGroup = this.createEmailForm();
  readonly isEmailSaving = signal(false);
  readonly emailError = signal<string | null>(null);
  readonly emailSuccess = signal<string | null>(null);

  readonly passwordForm: PasswordFormGroup = this.createPasswordForm();
  readonly isPasswordSaving = signal(false);
  readonly passwordError = signal<string | null>(null);
  readonly passwordSuccess = signal<string | null>(null);

  readonly twoFactorForm: TwoFactorFormGroup = this.createTwoFactorForm();
  readonly backupCodesForm: BackupCodesFormGroup = this.createBackupCodesForm();
  readonly disableTwoFactorForm: PasswordConfirmFormGroup = this.createPasswordConfirmForm();
  readonly logoutForm: PasswordConfirmFormGroup = this.createPasswordConfirmForm();

  private readonly healthAlertsDisplayed = new Set<string>();

  private readonly rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

  readonly createForm: KeyCreateFormGroup = this.createKeyForm();
  readonly editForm: KeyEditFormGroup = this.createEditForm();
  readonly deleteForm: KeyDeleteFormGroup = this.createDeleteForm();
  readonly isCreateCustomVenue = signal(false);
  readonly isEditCustomVenue = signal(false);
  readonly venueOptions = computed<ExchangeDescriptor[]>(() => this.computeVenueOptions());
  get isAdmin(): boolean {
    return this.user()?.isAdmin ?? false;
  }

  ngOnInit(): void {
    this.fetchKeys();
    void this.loadAssignmentContext();
    this.loadExchangeCatalog();
    this.loadAccountProfile();
    this.authState.initialize();
    this.bootstrapTwoFactorState();
  }

  setActiveTab(tab: 'account' | 'security' | 'api-keys'): void {
    this.activeTab.set(tab);
  }

  refresh(): void {
    this.fetchKeys({ silent: true });
  }

  openEmailDialog(): void {
    this.emailError.set(null);
    this.emailSuccess.set(null);
    this.emailForm.reset({ email: '', password: '' });
    this.emailForm.markAsPristine();
    this.emailForm.markAsUntouched();
    this.isEmailDialogOpen.set(true);
  }

  closeEmailDialog(): void {
    this.isEmailDialogOpen.set(false);
  }

  openPasswordDialog(): void {
    this.passwordError.set(null);
    this.passwordSuccess.set(null);
    this.passwordForm.reset({ currentPassword: '', password: '', confirmPassword: '' });
    this.passwordForm.markAsPristine();
    this.passwordForm.markAsUntouched();
    this.isPasswordDialogOpen.set(true);
  }

  closePasswordDialog(): void {
    this.isPasswordDialogOpen.set(false);
  }

  openLogoutDialog(): void {
    this.logoutError.set(null);
    this.logoutForm.reset({ password: '' });
    this.logoutForm.markAsPristine();
    this.logoutForm.markAsUntouched();
    this.isLogoutDialogOpen.set(true);
  }

  closeLogoutDialog(): void {
    this.isLogoutDialogOpen.set(false);
  }

  async logoutCurrentSession(): Promise<void> {
    this.authState.logout();
    this.notifications.info('You have been signed out.', 'Security');
  }

  openDisableTwoFactorDialog(): void {
    this.disableTwoFactorError.set(null);
    this.disableTwoFactorForm.reset({ password: '' });
    this.disableTwoFactorForm.markAsPristine();
    this.disableTwoFactorForm.markAsUntouched();
    this.isDisableTwoFactorDialogOpen.set(true);
  }

  closeDisableTwoFactorDialog(): void {
    this.isDisableTwoFactorDialogOpen.set(false);
  }

  toggleCreateAdvanced(): void {
    this.isCreateAdvancedOpen.update((current) => !current);
  }

  toggleEditAdvanced(): void {
    this.isEditAdvancedOpen.update((current) => !current);
  }

  showControlError(control: AbstractControl | null): boolean {
    return !!control && control.invalid && (control.touched || control.dirty);
  }

  fieldHasError(control: AbstractControl | null, errorCode: string): boolean {
    return !!control && control.hasError(errorCode) && (control.touched || control.dirty);
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
        this.ensureCreateVenueInitialized();
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
    this.emailError.set(null);
    this.emailSuccess.set(null);
    this.passwordError.set(null);
    this.passwordSuccess.set(null);
    this.usersApi.getAccount().subscribe({
      next: (profile) => {
        const account = profile ?? null;
        this.activeUser.set(account);

        const existingUser = this.authState.currentUser();
        if (account) {
          const merged = existingUser ? { ...existingUser, ...account } : (account as AuthUser);
          this.authState.setCurrentUser(merged);
        }

        if (this.isEmailDialogOpen()) {
          this.emailForm.reset({ email: '', password: '' });
          this.emailForm.markAsPristine();
          this.emailForm.markAsUntouched();
        }

        if (this.isPasswordDialogOpen()) {
          this.passwordForm.reset({
            currentPassword: '',
            password: '',
            confirmPassword: '',
          });
          this.passwordForm.markAsPristine();
          this.passwordForm.markAsUntouched();
        }
      },
      error: (error) => {
        this.handleError(error, this.emailError, 'Unable to load account profile.');
      },
    });
  }

  openCreateDialog(): void {
    this.resetCreateForm();
    this.createError.set(null);
    this.isCreateCustomVenue.set(false);
    this.ensureCreateVenueInitialized();
    this.isCreateAdvancedOpen.set(false);
    this.isCreateDialogOpen.set(true);
  }

  closeCreateDialog(): void {
    this.isCreateDialogOpen.set(false);
    this.resetCreateForm();
    this.isCreateAdvancedOpen.set(false);
  }

  openEditDialog(key: ApiKey): void {
    this.editDialogKey.set(key);
    this.resetEditForm(key);
    this.editError.set(null);
    this.isEditCustomVenue.set(!this.hasKnownVenue(key.venue));
    this.isEditAdvancedOpen.set(false);
    this.isEditDialogOpen.set(true);
  }

  closeEditDialog(): void {
    this.isEditDialogOpen.set(false);
    this.editDialogKey.set(null);
    this.resetEditForm();
    this.isEditAdvancedOpen.set(false);
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

  async changeEmail(): Promise<void> {
    this.emailError.set(null);
    this.emailSuccess.set(null);

    const currentUser = this.activeUser();
    if (!currentUser) {
      this.emailError.set('No user profile available.');
      return;
    }

    if (this.emailForm.invalid) {
      this.emailForm.markAllAsTouched();
      this.emailError.set('Enter a valid email address to continue.');
      return;
    }

    const newEmail = this.emailForm.controls.email.value.trim();
    const password = this.emailForm.controls.password.value.trim();
    if (!newEmail) {
      this.emailError.set('Enter a new email address to continue.');
      return;
    }

    if (newEmail.toLowerCase() === (currentUser.email ?? '').toLowerCase()) {
      this.emailError.set('That email is already associated with your account.');
      return;
    }

    if (!password) {
      this.emailError.set('Confirm the change with your password.');
      return;
    }

    this.isEmailSaving.set(true);
    try {
      await firstValueFrom(
        this.authApi.requestEmailChange({
          newEmail,
          password,
        }),
      );

      this.emailForm.reset({ email: '', password: '' });
      this.emailForm.markAsPristine();
      this.emailForm.markAsUntouched();

      this.emailSuccess.set(
        'Confirmation sent. Follow the verification link delivered to the new address to finish updating your login email.',
      );
      this.notifications.success('Check your inbox to confirm the new email address.', 'Settings');
      this.closeEmailDialog();
    } catch (error) {
      this.handleError(error, this.emailError, 'Failed to update email address.');
    } finally {
      this.isEmailSaving.set(false);
    }
  }

  async changePassword(): Promise<void> {
    this.passwordError.set(null);
    this.passwordSuccess.set(null);

    const currentUser = this.activeUser();
    if (!currentUser) {
      this.passwordError.set('No user profile available.');
      return;
    }

    if (this.passwordForm.invalid) {
      this.passwordForm.markAllAsTouched();
      this.passwordError.set('Fill in every field to update your password.');
      return;
    }

    const raw = this.passwordForm.getRawValue();
    const currentPassword = raw.currentPassword.trim();
    const newPassword = raw.password.trim();
    const confirmPassword = raw.confirmPassword.trim();

    if (!currentPassword) {
      this.passwordError.set('Current password is required to update your password.');
      return;
    }

    if (!newPassword) {
      this.passwordError.set('New password must be provided.');
      return;
    }

    if (newPassword.length < 8) {
      this.passwordError.set('Password must be at least 8 characters.');
      return;
    }

    if (newPassword !== confirmPassword) {
      this.passwordError.set('Password confirmation does not match.');
      return;
    }

    this.isPasswordSaving.set(true);
    try {
      const passwordPayload: PasswordUpdateRequest = {
        currentPassword,
        newPassword,
      };
      const currentUser = this.authState.currentUser();
      if (!currentUser) {
        throw new Error('No active session found. Please sign in again.');
      }

      await firstValueFrom(this.usersApi.changePassword(passwordPayload));
      const latestAccount = await firstValueFrom(this.usersApi.getAccount());
      this.activeUser.set(latestAccount);
      this.authState.setCurrentUser({ ...currentUser, ...latestAccount });

      this.passwordForm.reset({
        currentPassword: '',
        password: '',
        confirmPassword: '',
      });
      this.passwordForm.markAsPristine();
      this.passwordForm.markAsUntouched();

      this.passwordSuccess.set('Password updated successfully.');
      this.notifications.success('Password updated.', 'Settings');
      this.closePasswordDialog();
    } catch (error) {
      this.handleError(error, this.passwordError, 'Failed to update password.');
    } finally {
      this.isPasswordSaving.set(false);
    }
  }

  async enableTwoFactor(): Promise<void> {
    this.twoFactorError.set(null);
    if (this.twoFactorForm.invalid) {
      this.twoFactorForm.markAllAsTouched();
      this.twoFactorError.set('Enter the 6-digit code from your authenticator app.');
      return;
    }

    const code = this.twoFactorForm.controls.code.value.trim();
    if (!/^\d{6}$/.test(code)) {
      this.twoFactorError.set('Two-factor codes are 6 digits.');
      return;
    }

    this.isTwoFactorSubmitting.set(true);
    try {
      const response = await firstValueFrom(this.authApi.enableMfa({ code }));
      this.setBackupCodes(
        response.backupCodes,
        response.detail || 'Two-factor authentication enabled.',
      );
      this.twoFactorForm.reset({ code: '' });
      this.twoFactorForm.markAsPristine();
      this.twoFactorForm.markAsUntouched();
      this.twoFactorSecret.set(null);
      this.twoFactorQr.set(null);
      this.twoFactorSetupError.set(null);
      this.isTwoFactorEnabled.set(true);
      this.notifications.success('Two-factor authentication enabled.', 'Security');
      this.bootstrapTwoFactorState();
    } catch (error) {
      this.handleError(error, this.twoFactorError, 'Failed to enable two-factor authentication.');
    } finally {
      this.isTwoFactorSubmitting.set(false);
    }
  }

  async regenerateTwoFactorBackupCodes(): Promise<void> {
    this.twoFactorBackupCodesError.set(null);
    this.twoFactorBackupCodesSuccess.set(null);

    if (!this.isTwoFactorEnabled()) {
      this.twoFactorBackupCodesError.set('Enable two-factor authentication first.');
      return;
    }

    const { code, password } = this.backupCodesForm.value;
    const trimmedCode = code?.trim() ?? '';
    const trimmedPassword = password?.trim() ?? '';

    if (!trimmedCode && !trimmedPassword) {
      this.twoFactorBackupCodesError.set('Enter your password or a valid code to continue.');
      this.backupCodesForm.markAllAsTouched();
      return;
    }

    this.isBackupCodesLoading.set(true);
    try {
      const payload: MfaBackupCodesRequest = {};
      if (trimmedCode) {
        payload.code = trimmedCode;
      }
      if (trimmedPassword) {
        payload.password = trimmedPassword;
      }
      const response = await firstValueFrom(this.authApi.regenerateBackupCodes(payload));
      this.setBackupCodes(
        response.backupCodes,
        response.detail || 'Backup codes regenerated.',
      );
      this.notifications.success('Backup codes regenerated.', 'Security');
      this.backupCodesForm.reset({ code: '', password: '' });
      this.backupCodesForm.markAsPristine();
      this.backupCodesForm.markAsUntouched();
    } catch (error) {
      this.handleError(error, this.twoFactorBackupCodesError, 'Unable to regenerate backup codes.');
    } finally {
      this.isBackupCodesLoading.set(false);
    }
  }

  async copyBackupCodes(): Promise<void> {
    const codes = this.twoFactorBackupCodes();
    if (!codes.length) {
      return;
    }

    if (!('clipboard' in navigator)) {
      this.twoFactorBackupCodesError.set('Clipboard access is not available in this environment.');
      return;
    }

    try {
      await navigator.clipboard.writeText(codes.join('\n'));
      const message = 'Backup codes copied to clipboard.';
      this.twoFactorBackupCodesSuccess.set(message);
      this.twoFactorBackupCodesError.set(null);
      this.notifications.success(message, 'Security');
    } catch (error) {
      console.error(error);
      this.twoFactorBackupCodesError.set('Unable to copy backup codes. Copy them manually.');
      this.notifications.error('Unable to copy backup codes.', 'Security');
    }
  }

  downloadBackupCodes(): void {
    const codes = this.twoFactorBackupCodes();
    if (!codes.length) {
      return;
    }

    const timestamp = new Date().toISOString().replace(/[:T]/g, '-').split('.')[0];
    const filename = `amadeus-backup-codes-${timestamp}.txt`;
    const blob = new Blob([codes.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
    this.twoFactorBackupCodesSuccess.set('Backup codes downloaded.');
    this.twoFactorBackupCodesError.set(null);
    this.notifications.success('Backup codes downloaded.', 'Security');
  }

  async disableTwoFactorConfirmed(): Promise<void> {
    if (this.disableTwoFactorForm.invalid) {
      this.disableTwoFactorForm.markAllAsTouched();
      this.disableTwoFactorError.set('Enter your password to continue.');
      return;
    }

    const password = this.disableTwoFactorForm.controls.password.value.trim();
    if (!password) {
      this.disableTwoFactorError.set('Enter your password to continue.');
      return;
    }

    this.isDisableTwoFactorSubmitting.set(true);
    this.disableTwoFactorError.set(null);
    try {
      await firstValueFrom(this.authApi.disableMfa({ password }));
      this.notifications.info('Two-factor authentication disabled.', 'Security');
      this.isTwoFactorEnabled.set(false);
      this.closeDisableTwoFactorDialog();
      this.disableTwoFactorForm.reset({ password: '' });
      this.disableTwoFactorForm.markAsPristine();
      this.disableTwoFactorForm.markAsUntouched();
      this.twoFactorForm.reset({ code: '' });
      this.twoFactorForm.markAsPristine();
      this.twoFactorForm.markAsUntouched();
      this.twoFactorSecret.set(null);
      this.twoFactorQr.set(null);
      this.twoFactorSetupError.set(null);
      this.clearBackupCodesState();
      this.bootstrapTwoFactorState();
    } catch (error) {
      this.handleError(error, this.disableTwoFactorError, 'Unable to disable two-factor authentication.');
    } finally {
      this.isDisableTwoFactorSubmitting.set(false);
    }
  }

  async revokeSessions(): Promise<void> {
    if (this.logoutForm.invalid) {
      this.logoutForm.markAllAsTouched();
      this.logoutError.set('Enter your password to revoke other sessions.');
      return;
    }

    const password = this.logoutForm.controls.password.value.trim();
    if (!password) {
      this.logoutError.set('Enter your password to revoke other sessions.');
      return;
    }

    this.isLogoutSubmitting.set(true);
    this.logoutError.set(null);
    try {
      await firstValueFrom(this.authApi.revokeAllSessions({ password }));
      this.notifications.success('Other sessions have been signed out.', 'Security');
      this.logoutForm.reset({ password: '' });
      this.logoutForm.markAsPristine();
      this.logoutForm.markAsUntouched();
      this.closeLogoutDialog();
    } catch (error) {
      this.handleError(error, this.logoutError, 'Unable to revoke other sessions.');
    } finally {
      this.isLogoutSubmitting.set(false);
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

    const label = raw.label.trim();
    const venue = raw.venue.trim() || this.pickDefaultVenue();
    const apiKey = raw.apiKey.trim();
    const apiSecret = raw.apiSecret.trim();
    const passphrase = raw.passphrase.trim();

    if (!venue || !apiKey || !apiSecret || !passphrase) {
      this.createError.set('Fill in all required fields.');
      return;
    }

    const keyId = this.generateKeyIdentifier(label, apiKey);
    if (!keyId) {
      this.createError.set('Unable to generate a key identifier.');
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
      const trimmedLabel = raw.label.trim();
      const payload: KeyUpdateRequest = {
        venue,
        scopes,
        passphraseHash,
        label: trimmedLabel,
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
        const selectedRaw = selections.hasOwnProperty(adapter.selectionKey)
          ? selections[adapter.selectionKey]
          : adapter.assignedKeyId && adapter.assignedKeyId.length > 0
          ? adapter.assignedKeyId
          : null;
        const selected = selectedRaw ?? null;
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
          assignedKeyId: selected ?? '',
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
      this.ensureCreateVenueInitialized();

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
        const context = this.buildNodeAssignmentContext(detail);
        contexts.push(context);
        context.adapters.forEach((adapter) => {
          selections[adapter.selectionKey] = adapter.assignedKeyId && adapter.assignedKeyId.length > 0
            ? adapter.assignedKeyId
            : null;
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

  private buildNodeAssignmentContext(detail: NodeDetailResponse): NodeAssignmentContext {
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
        this.ensureCreateVenueInitialized();
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

  private createEmailForm(): EmailFormGroup {
    return this.fb.group({
      email: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.email],
      }),
      password: this.fb.nonNullable.control('', {
        validators: [Validators.required],
      }),
    });
  }

  private createPasswordForm(): PasswordFormGroup {
    return this.fb.group({
      currentPassword: this.fb.nonNullable.control('', {
        validators: [Validators.required],
      }),
      password: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.minLength(8)],
      }),
      confirmPassword: this.fb.nonNullable.control('', {
        validators: [Validators.required],
      }),
    });
  }

  private createBackupCodesForm(): BackupCodesFormGroup {
    return this.fb.group({
      code: this.fb.nonNullable.control(''),
      password: this.fb.nonNullable.control(''),
    });
  }

  private createTwoFactorForm(): TwoFactorFormGroup {
    return this.fb.group({
      code: this.fb.nonNullable.control('', {
        validators: [Validators.required, Validators.pattern(/^\d{6}$/)],
      }),
    });
  }

  private createPasswordConfirmForm(): PasswordConfirmFormGroup {
    return this.fb.group({
      password: this.fb.nonNullable.control('', {
        validators: [Validators.required],
      }),
    });
  }

  private createKeyForm(): KeyCreateFormGroup {
    return this.fb.group({
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
      label: '',
      venue: this.pickDefaultVenue(),
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
    const currentVenue = this.createForm.controls.venue.value;
    this.isCreateCustomVenue.set(!!currentVenue && !this.hasKnownVenue(currentVenue));
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

  private pickDefaultVenue(): string {
    const options = this.venueOptions();
    const [first] = options;
    return first?.code ?? '';
  }

  private ensureCreateVenueInitialized(): void {
    const control = this.createForm.controls.venue;
    const currentValue = control.value?.trim();
    if (currentValue) {
      return;
    }
    if (this.isCreateDialogOpen() && this.isCreateCustomVenue()) {
      return;
    }
    const defaultVenue = this.pickDefaultVenue();
    if (defaultVenue) {
      control.setValue(defaultVenue);
      this.isCreateCustomVenue.set(false);
    }
  }

  private generateKeyIdentifier(label: string, apiKey: string): string {
    const normalizedLabel = label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/-{2,}/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 48);
    let base = normalizedLabel;
    if (!base) {
      const sanitizedKey = apiKey.replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
      base = sanitizedKey.slice(0, 24);
    }
    if (!base) {
      base = `key-${Date.now().toString(36)}`;
    }
    return this.ensureUniqueKeyId(base);
  }

  private ensureUniqueKeyId(base: string): string {
    const maxLength = 64;
    const normalizedBase = base.slice(0, maxLength);
    const existingIds = new Set(this.keys().map((key) => key.key_id));
    if (!existingIds.has(normalizedBase)) {
      return normalizedBase;
    }

    let counter = 2;
    while (true) {
      const suffix = `-${counter}`;
      const truncated = normalizedBase.slice(0, Math.max(1, maxLength - suffix.length));
      const candidate = `${truncated}${suffix}`;
      if (!existingIds.has(candidate)) {
        return candidate;
      }
      counter += 1;
    }
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

  private clearBackupCodesState(): void {
    this.twoFactorBackupCodes.set([]);
    this.twoFactorBackupCodesError.set(null);
    this.twoFactorBackupCodesSuccess.set(null);
    this.backupCodesForm.reset({ code: '', password: '' });
    this.backupCodesForm.markAsPristine();
    this.backupCodesForm.markAsUntouched();
  }

  private setBackupCodes(codes: readonly string[], detail?: string): void {
    const sanitized = codes.map((code) => code.trim()).filter((code) => code.length > 0);
    this.twoFactorBackupCodes.set(sanitized);
    if (sanitized.length > 0) {
      this.twoFactorBackupCodesSuccess.set(
        detail ?? 'Store these backup codes in a secure location.',
      );
    } else {
      this.twoFactorBackupCodesSuccess.set(detail ?? null);
    }
    this.twoFactorBackupCodesError.set(null);
  }

  private bootstrapTwoFactorState(): void {
    this.isTwoFactorLoading.set(true);
    this.twoFactorError.set(null);
    this.twoFactorSetupError.set(null);

    this.authApi.getCurrentUser().subscribe({
      next: (user) => {
        this.authUser.set(user);
        this.authState.setCurrentUser(user);
        this.isTwoFactorEnabled.set(Boolean(user.mfaEnabled));
        if (user.mfaEnabled) {
          this.twoFactorSecret.set(null);
          this.twoFactorQr.set(null);
          this.twoFactorForm.reset({ code: '' });
          this.twoFactorForm.markAsPristine();
          this.twoFactorForm.markAsUntouched();
          this.isTwoFactorLoading.set(false);
        } else {
          this.clearBackupCodesState();
          this.startTwoFactorEnrollment();
        }
      },
      error: (error) => {
        this.handleError(error, this.twoFactorSetupError, 'Unable to load two-factor settings.');
        this.isTwoFactorLoading.set(false);
      },
    });
  }

  private startTwoFactorEnrollment(): void {
    this.isTwoFactorLoading.set(true);
    this.twoFactorSetupError.set(null);
    this.twoFactorError.set(null);
    this.twoFactorSecret.set(null);
    this.twoFactorQr.set(null);
    this.twoFactorForm.reset({ code: '' });
    this.twoFactorForm.markAsPristine();
    this.twoFactorForm.markAsUntouched();
    this.clearBackupCodesState();

    this.authApi.setupMfa().subscribe({
      next: (response) => {
        this.twoFactorSecret.set(response.secret);
        void this.renderTwoFactorQr(response.otpauthUrl);
      },
      error: (error) => {
        this.handleError(error, this.twoFactorSetupError, 'Unable to prepare two-factor secret.');
        this.isTwoFactorLoading.set(false);
      },
    });
  }

  private async renderTwoFactorQr(otpauthUrl: string): Promise<void> {
    try {
      const qr = await toDataURL(otpauthUrl, { margin: 1, width: 240 });
      this.twoFactorQr.set(qr);
      this.twoFactorSetupError.set(null);
    } catch (error) {
      console.error(error);
      this.twoFactorSetupError.set(
        'Unable to render the QR code. Enter the secret manually in your authenticator app.',
      );
    } finally {
      this.isTwoFactorLoading.set(false);
    }
  }
}
