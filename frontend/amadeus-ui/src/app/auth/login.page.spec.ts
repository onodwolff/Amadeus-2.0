import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { AuthService, PasswordLoginError } from './auth.service';
import { LoginPage } from './login.page';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { AuthUser, MfaChallengeResponse } from '../api/models';

describe('LoginPage', () => {
  let fixture: ComponentFixture<LoginPage>;
  let component: LoginPage;
  let authService: jasmine.SpyObj<AuthService>;
  let router: jasmine.SpyObj<Router>;
  let getItemSpy: jasmine.Spy;
  let setItemSpy: jasmine.Spy;
  let removeItemSpy: jasmine.Spy;

  const createUser = (): AuthUser => ({
    id: 1,
    email: 'user@example.com',
    username: 'user',
    name: 'Example User',
    roles: ['member'],
    permissions: [],
    active: true,
    isAdmin: false,
    emailVerified: true,
    mfaEnabled: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    lastLoginAt: new Date().toISOString(),
  });

  const createAuthStateStub = () =>
    ({
      currentUser: signal<AuthUser | null>(null),
    } as unknown as AuthStateService);

  beforeAll(() => {
    getItemSpy = spyOn(window.localStorage, 'getItem').and.returnValue(null);
    setItemSpy = spyOn(window.localStorage, 'setItem');
    removeItemSpy = spyOn(window.localStorage, 'removeItem');
  });

  beforeEach(async () => {
    getItemSpy.calls.reset();
    setItemSpy.calls.reset();
    removeItemSpy.calls.reset();
    getItemSpy.and.returnValue(null);

    authService = jasmine.createSpyObj<AuthService>('AuthService', ['loginWithPassword']);
    router = jasmine.createSpyObj<Router>('Router', ['navigateByUrl', 'navigate']);
    router.navigateByUrl.and.returnValue(Promise.resolve(true));
    router.navigate.and.returnValue(Promise.resolve(true));

    await TestBed.configureTestingModule({
      imports: [LoginPage],
      providers: [
        { provide: AuthService, useValue: authService },
        { provide: Router, useValue: router },
        { provide: AuthStateService, useFactory: createAuthStateStub },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LoginPage);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('submits credentials and navigates to the dashboard when authentication succeeds', async () => {
    authService.loginWithPassword.and.returnValue(
      Promise.resolve({
        kind: 'authenticated',
        user: createUser(),
      }),
    );

    component['form'].setValue({
      identifier: 'user@example.com',
      password: 'StrongPass!1',
      rememberMe: true,
    });

    await component['submit']();

    expect(authService.loginWithPassword).toHaveBeenCalledWith({
      identifier: 'user@example.com',
      password: 'StrongPass!1',
      rememberMe: true,
    });
    expect(router.navigateByUrl).toHaveBeenCalledWith('/dashboard');
    expect(setItemSpy).toHaveBeenCalledWith('amadeus:last-login-identifier', 'user@example.com');
    expect(removeItemSpy).not.toHaveBeenCalled();
  });

  it('prevents submission when required fields are missing', async () => {
    component['form'].setValue({ identifier: '', password: '', rememberMe: true });

    await component['submit']();

    expect(authService.loginWithPassword).not.toHaveBeenCalled();
    expect(component['error']()).toBe('Check the highlighted fields and try again.');
  });

  it('shows backend errors returned by the authentication service', async () => {
    authService.loginWithPassword.and.returnValue(
      Promise.reject(new PasswordLoginError('Invalid credentials.', 401)),
    );

    component['form'].setValue({
      identifier: 'user@example.com',
      password: 'wrong',
      rememberMe: false,
    });

    await component['submit']();

    expect(component['error']()).toBe('Invalid credentials.');
    expect(removeItemSpy).toHaveBeenCalledWith('amadeus:last-login-identifier');
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('redirects to MFA challenge when additional verification is required', async () => {
    const challenge: MfaChallengeResponse = {
      challengeToken: 'challenge-token',
      detail: 'Enter your authenticator code.',
      methods: ['totp'],
      ttlSeconds: 120,
    };
    authService.loginWithPassword.and.returnValue(
      Promise.resolve({
        kind: 'mfa-required',
        challenge,
      }),
    );

    component['form'].setValue({
      identifier: 'user@example.com',
      password: 'StrongPass!1',
      rememberMe: true,
    });

    await component['submit']();

    expect(router.navigate).toHaveBeenCalledWith(['/login/mfa'], {
      queryParams: {
        token: 'challenge-token',
        detail: 'Enter your authenticator code.',
      },
    });
    expect(setItemSpy).toHaveBeenCalledWith('amadeus:last-login-identifier', 'user@example.com');
  });
});
