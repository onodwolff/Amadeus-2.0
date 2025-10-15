import { provideZonelessChangeDetection, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';

import { AuthApi } from '../api/clients/auth.api';
import { IntegrationsApi } from '../api/clients/integrations.api';
import { KeysApi } from '../api/clients/keys.api';
import { MarketApi } from '../api/clients/market.api';
import { NodesApi } from '../api/clients/nodes.api';
import { UsersApi } from '../api/clients/users.api';
import { ApiKey, AuthUser, ExchangeDescriptor, UserProfile } from '../api/models';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { NotificationService } from '../shared/notifications/notification.service';
import { SettingsPage } from './settings.page';

function createAuthUser(): AuthUser {
  const timestamp = new Date().toISOString();
  return {
    id: 1,
    email: 'user@example.com',
    username: 'user',
    name: 'Example User',
    roles: ['member'],
    permissions: ['gateway.users.manage', 'gateway.users.view'],
    active: true,
    isAdmin: false,
    emailVerified: true,
    mfaEnabled: false,
    createdAt: timestamp,
    updatedAt: timestamp,
    lastLoginAt: timestamp,
  };
}

function createUserProfile(): UserProfile {
  const timestamp = new Date().toISOString();
  return {
    id: 1,
    email: 'user@example.com',
    username: 'user',
    name: 'Example User',
    roles: ['member'],
    permissions: ['gateway.users.manage', 'gateway.users.view'],
    active: true,
    isAdmin: false,
    createdAt: timestamp,
    updatedAt: timestamp,
    lastLoginAt: timestamp,
  };
}

describe('SettingsPage advanced settings', () => {
  let fixture: ComponentFixture<SettingsPage>;
  let component: SettingsPage;
  let authApiStub: jasmine.SpyObj<AuthApi>;
  let usersApiStub: jasmine.SpyObj<UsersApi>;
  let notificationServiceStub: jasmine.SpyObj<NotificationService>;
  let authStateStub: Partial<AuthStateService>;
  let currentUserSignal: WritableSignal<AuthUser | null>;
  let permissionsSignal: WritableSignal<string[]>;
  let routerStub: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    authApiStub = jasmine.createSpyObj<AuthApi>('AuthApi', [
      'requestEmailChange',
      'enableMfa',
      'disableMfa',
      'revokeAllSessions',
      'getCurrentUser',
      'setupMfa',
      'regenerateBackupCodes',
      'completeMfaLogin',
    ]);
    authApiStub.requestEmailChange.and.returnValue(of({ verificationToken: 'token' }));
    authApiStub.enableMfa.and.returnValue(of({ detail: 'ok', backupCodes: ['CODE-1'] }));
    authApiStub.disableMfa.and.returnValue(of({ detail: 'ok' }));
    authApiStub.revokeAllSessions.and.returnValue(of({ detail: 'ok' }));
    authApiStub.getCurrentUser.and.returnValue(of(createAuthUser()));
    authApiStub.setupMfa.and.returnValue(of({ secret: 'secret', otpauthUrl: 'url' }));
    authApiStub.regenerateBackupCodes.and.returnValue(of({ detail: 'ok', backupCodes: ['CODE-2'] }));
    authApiStub.completeMfaLogin.and.returnValue(
      of({
        accessToken: 'token',
        tokenType: 'bearer',
        expiresIn: 900,
        refreshExpiresAt: new Date().toISOString(),
        user: createAuthUser(),
      }),
    );

    const keysApiStub = jasmine.createSpyObj<KeysApi>('KeysApi', [
      'listKeys',
      'createKey',
      'updateKey',
      'deleteKey',
    ]);
    keysApiStub.listKeys.and.returnValue(of({ keys: [] }));
    keysApiStub.createKey.and.returnValue(
      of({
        key_id: 'generated',
        venue: 'BINANCE',
        scopes: [],
        created_at: new Date().toISOString(),
      }),
    );
    keysApiStub.updateKey.and.returnValue(
      of({
        key_id: 'generated',
        venue: 'BINANCE',
        scopes: [],
        created_at: new Date().toISOString(),
      }),
    );
    keysApiStub.deleteKey.and.returnValue(of(void 0));

    const nodesApiStub = jasmine.createSpyObj<NodesApi>('NodesApi', ['listNodes', 'getNodeDetail']);
    nodesApiStub.listNodes.and.returnValue(of({ nodes: [] }));
    nodesApiStub.getNodeDetail.and.returnValue(
      of({
        node: {
          id: 'node-1',
          mode: 'live',
          status: 'running',
          adapters: [],
        },
        config: {},
        lifecycle: [],
      }),
    );

    const marketApiStub = jasmine.createSpyObj<MarketApi>('MarketApi', ['listInstruments']);
    marketApiStub.listInstruments.and.returnValue(of({ instruments: [] }));

    usersApiStub = jasmine.createSpyObj<UsersApi>('UsersApi', [
      'getAccount',
      'updatePassword',
      'changePassword',
    ]);
    usersApiStub.getAccount.and.returnValue(of(createUserProfile()));
    usersApiStub.updatePassword.and.returnValue(of(createUserProfile()));
    usersApiStub.changePassword.and.returnValue(of(void 0));

    const integrationsApiStub = jasmine.createSpyObj<IntegrationsApi>('IntegrationsApi', ['listExchanges']);
    integrationsApiStub.listExchanges.and.returnValue(of({ exchanges: [] as ExchangeDescriptor[] }));

    notificationServiceStub = jasmine.createSpyObj<NotificationService>('NotificationService', [
      'success',
      'info',
      'warning',
      'error',
    ]);

    currentUserSignal = signal<AuthUser | null>(createAuthUser());
    permissionsSignal = signal<string[]>(createAuthUser().permissions);

    authStateStub = {
      initialize: jasmine.createSpy('initialize'),
      setCurrentUser: jasmine.createSpy('setCurrentUser'),
      clear: jasmine.createSpy('clear'),
      logout: jasmine.createSpy('logout'),
      currentUser: currentUserSignal,
      permissions: permissionsSignal,
    };

    routerStub = jasmine.createSpyObj<Router>('Router', ['navigate']);
    routerStub.navigate.and.returnValue(Promise.resolve(true));

    await TestBed.configureTestingModule({
      imports: [SettingsPage, RouterTestingModule],
      providers: [
        provideZonelessChangeDetection(),
        { provide: AuthApi, useValue: authApiStub },
        { provide: KeysApi, useValue: keysApiStub },
        { provide: NodesApi, useValue: nodesApiStub },
        { provide: MarketApi, useValue: marketApiStub },
        { provide: UsersApi, useValue: usersApiStub },
        { provide: IntegrationsApi, useValue: integrationsApiStub },
        { provide: NotificationService, useValue: notificationServiceStub },
        { provide: AuthStateService, useValue: authStateStub as AuthStateService },
        { provide: Router, useValue: routerStub },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(SettingsPage);
    component = fixture.componentInstance;
    component.ngOnInit = () => {};
    component.availableExchanges.set([{ code: 'BINANCE', name: 'Binance' }]);
  });

  it('renders exit button that logs out the current session', async () => {
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const exitButton = host.querySelector('[data-testid="settings-exit"]') as HTMLButtonElement | null;

    expect(exitButton).withContext('exit button should be rendered').not.toBeNull();

    exitButton?.click();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(authStateStub.logout).toHaveBeenCalled();
    expect(routerStub.navigate).not.toHaveBeenCalled();
    expect(notificationServiceStub.info).toHaveBeenCalledWith('You have been signed out.', 'Security');
  });

  it('logs out current session and redirects to login', async () => {
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const logoutButton = host.querySelector('[data-testid="logout-current-session"]') as HTMLButtonElement | null;

    expect(logoutButton).withContext('log out button should be rendered').not.toBeNull();

    logoutButton?.click();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(authStateStub.logout).toHaveBeenCalled();
    expect(routerStub.navigate).not.toHaveBeenCalled();
    expect(notificationServiceStub.info).toHaveBeenCalledWith('You have been signed out.', 'Security');
  });

  it('should hide create dialog advanced settings until expanded', () => {
    component.openCreateDialog();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const createPanel = host.querySelector('[aria-labelledby="createKeyTitle"]');
    expect(createPanel).withContext('create dialog should be present').not.toBeNull();
    expect(createPanel?.querySelector('.dialog__advanced')).toBeNull();

    const toggle = createPanel?.querySelector('.dialog__toggle') as HTMLButtonElement;
    toggle.click();
    fixture.detectChanges();

    const advanced = createPanel?.querySelector('.dialog__advanced') as HTMLElement | null;
    expect(advanced).withContext('advanced section should be visible').not.toBeNull();
    expect(advanced?.querySelector('[formControlName="label"]')).not.toBeNull();
    expect(advanced?.querySelector('[formControlName="passphraseHint"]')).not.toBeNull();
  });

  it('should group edit dialog optional fields inside advanced settings', () => {
    const key: ApiKey = {
      key_id: 'key-1',
      venue: 'BINANCE',
      scopes: ['read', 'trade'],
      created_at: new Date().toISOString(),
      label: 'Primary key',
      passphrase_hint: 'Hint',
    };

    component.openEditDialog(key);
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const editPanel = host.querySelector('[aria-labelledby="editKeyTitle"]');
    expect(editPanel).withContext('edit dialog should be present').not.toBeNull();
    expect(editPanel?.querySelector('.dialog__advanced')).toBeNull();

    const toggle = editPanel?.querySelector('.dialog__toggle') as HTMLButtonElement;
    toggle.click();
    fixture.detectChanges();

    const advanced = editPanel?.querySelector('.dialog__advanced') as HTMLElement | null;
    expect(advanced).withContext('advanced section should be visible').not.toBeNull();
    expect(advanced?.querySelector('[formControlName="label"]')).not.toBeNull();
    expect(advanced?.querySelector('[formControlName="passphraseHint"]')).not.toBeNull();
  });

  it('allows viewer users to change their own password', async () => {
    const viewer = {
      ...createAuthUser(),
      permissions: ['gateway.users.view'],
      roles: ['viewer'],
    };
    currentUserSignal.set(viewer);
    permissionsSignal.set(viewer.permissions);

    component.passwordForm.setValue({
      currentPassword: 'current-password',
      password: 'new-password',
      confirmPassword: 'new-password',
    });

    await component.changePassword();

    expect(usersApiStub.changePassword).toHaveBeenCalledWith({
      currentPassword: 'current-password',
      newPassword: 'new-password',
    });
    expect(usersApiStub.updatePassword).not.toHaveBeenCalled();
    expect(usersApiStub.getAccount).toHaveBeenCalled();
    expect(authStateStub.setCurrentUser).toHaveBeenCalledWith(
      jasmine.objectContaining({ id: viewer.id }),
    );
  });

  it('should surface helper guidance for credential secrets and passphrases', () => {
    component.openCreateDialog();
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const createPanel = host.querySelector('[aria-labelledby="createKeyTitle"]') as HTMLElement | null;
    expect(createPanel).withContext('create dialog should be present').not.toBeNull();

    const secretHelp = createPanel?.querySelector('#create-api-secret-help');
    expect(secretHelp?.textContent ?? '').toContain('Paste the exact secret string issued by your exchange');

    const passphraseHelp = createPanel?.querySelector('#create-passphrase-help');
    expect(passphraseHelp?.textContent ?? '').toContain('Use a unique passphrase with eight or more characters');
  });

  it('should display validation feedback when credential fields are invalid', () => {
    component.openCreateDialog();
    fixture.detectChanges();

    component.createForm.controls.apiSecret.markAsTouched();
    component.createForm.controls.apiSecret.setValue('');
    component.createForm.controls.apiSecret.updateValueAndValidity();

    component.createForm.controls.passphrase.setValue('short');
    component.createForm.controls.passphrase.markAsTouched();
    component.createForm.controls.passphrase.updateValueAndValidity();

    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const createPanel = host.querySelector('[aria-labelledby="createKeyTitle"]') as HTMLElement | null;
    expect(createPanel).withContext('create dialog should be present').not.toBeNull();

    expect(createPanel?.querySelector('[data-testid="create-api-secret-error-required"]')).not.toBeNull();
    expect(createPanel?.querySelector('[data-testid="create-passphrase-error-minlength"]')).not.toBeNull();
    expect(createPanel?.querySelector('[data-testid="create-passphrase-error-required"]')).toBeNull();
  });

  it('enables two-factor authentication and stores backup codes', async () => {
    component.twoFactorSecret.set('secret');
    authApiStub.getCurrentUser.and.returnValue(
      of({
        ...createAuthUser(),
        mfaEnabled: true,
      }),
    );

    component.twoFactorForm.setValue({ code: '123456' });

    await component.enableTwoFactor();

    expect(authApiStub.enableMfa).toHaveBeenCalledWith({ code: '123456' });
    expect(component.twoFactorBackupCodes()).toEqual(['CODE-1']);
    expect(component.twoFactorBackupCodesSuccess()).toBe('ok');
    expect(component.isTwoFactorEnabled()).toBeTrue();
    expect(notificationServiceStub.success).toHaveBeenCalledWith(
      'Two-factor authentication enabled.',
      'Security',
    );
  });

  it('regenerates backup codes after verifying account credentials', async () => {
    component.isTwoFactorEnabled.set(true);
    component.backupCodesForm.setValue({ code: '', password: 'hunter2' });

    await component.regenerateTwoFactorBackupCodes();

    expect(authApiStub.regenerateBackupCodes).toHaveBeenCalledWith({ password: 'hunter2' });
    expect(component.twoFactorBackupCodes()).toEqual(['CODE-2']);
    expect(component.twoFactorBackupCodesSuccess()).toBe('ok');
    expect(component.backupCodesForm.value).toEqual({ code: '', password: '' });
    expect(notificationServiceStub.success).toHaveBeenCalledWith('Backup codes regenerated.', 'Security');
  });
});
