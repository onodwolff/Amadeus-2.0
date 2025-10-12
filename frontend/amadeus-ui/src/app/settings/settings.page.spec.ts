import { provideZonelessChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

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
  return {
    id: 'user-1',
    email: 'user@example.com',
    active: true,
    isAdmin: false,
    emailVerified: true,
    mfaEnabled: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    lastLoginAt: new Date().toISOString(),
  };
}

function createUserProfile(): UserProfile {
  return {
    id: 'user-1',
    name: 'Test User',
    email: 'user@example.com',
    role: 'member',
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

describe('SettingsPage advanced settings', () => {
  let fixture: ComponentFixture<SettingsPage>;
  let component: SettingsPage;

  beforeEach(async () => {
    const authApiStub = jasmine.createSpyObj<AuthApi>('AuthApi', [
      'requestEmailChange',
      'enableMfa',
      'disableMfa',
      'revokeAllSessions',
      'getCurrentUser',
      'setupMfa',
    ]);
    authApiStub.requestEmailChange.and.returnValue(of({ verificationToken: 'token' }));
    authApiStub.enableMfa.and.returnValue(of({ detail: 'ok' }));
    authApiStub.disableMfa.and.returnValue(of({ detail: 'ok' }));
    authApiStub.revokeAllSessions.and.returnValue(of({ detail: 'ok' }));
    authApiStub.getCurrentUser.and.returnValue(of(createAuthUser()));
    authApiStub.setupMfa.and.returnValue(of({ secret: 'secret', otpauthUrl: 'url' }));

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

    const usersApiStub = jasmine.createSpyObj<UsersApi>('UsersApi', ['getAccount', 'updatePassword']);
    usersApiStub.getAccount.and.returnValue(of({ account: createUserProfile() }));
    usersApiStub.updatePassword.and.returnValue(of({ account: createUserProfile() }));

    const integrationsApiStub = jasmine.createSpyObj<IntegrationsApi>('IntegrationsApi', ['listExchanges']);
    integrationsApiStub.listExchanges.and.returnValue(of({ exchanges: [] as ExchangeDescriptor[] }));

    const notificationServiceStub = jasmine.createSpyObj<NotificationService>(
      'NotificationService',
      ['success', 'info', 'warning', 'error'],
    );

    const authStateStub: Partial<AuthStateService> = {
      initialize: jasmine.createSpy('initialize'),
      setCurrentUser: jasmine.createSpy('setCurrentUser'),
      clear: jasmine.createSpy('clear'),
      isAdmin: signal(false),
    };

    await TestBed.configureTestingModule({
      imports: [SettingsPage],
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
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(SettingsPage);
    component = fixture.componentInstance;
    component.ngOnInit = () => {};
    component.availableExchanges.set([{ code: 'BINANCE', name: 'Binance' }]);
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
});
