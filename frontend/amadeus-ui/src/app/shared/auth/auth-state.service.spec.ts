import { TestBed } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';

import { AuthStateService } from './auth-state.service';
import { AuthService } from '../../auth/auth.service';
import { AuthUser } from '../../api/models';

describe('AuthStateService', () => {
  let service: AuthStateService;
  let bootstrapResolve: (() => void) | undefined;
  let bootstrapPromise: Promise<void>;
  let currentUserSignal: WritableSignal<AuthUser | null>;
  let isBootstrappedSignal: WritableSignal<boolean>;
  let authServiceStub: (Partial<AuthService> & {
    bootstrapMe: jasmine.Spy<() => Promise<void>>;
    setCurrentUser: jasmine.Spy<(user: AuthUser | null) => void>;
    logout: jasmine.Spy<() => void>;
  });

  beforeEach(() => {
    bootstrapPromise = new Promise<void>(resolve => {
      bootstrapResolve = resolve;
    });

    currentUserSignal = signal<AuthUser | null>(null);
    isBootstrappedSignal = signal(false);

    authServiceStub = {
      currentUser: currentUserSignal.asReadonly(),
      isBootstrapped: isBootstrappedSignal.asReadonly(),
      bootstrapMe: jasmine
        .createSpy('bootstrapMe')
        .and.callFake(() => bootstrapPromise),
      setCurrentUser: jasmine.createSpy('setCurrentUser'),
      logout: jasmine.createSpy('logout'),
    } satisfies Partial<AuthService> & {
      bootstrapMe: jasmine.Spy<() => Promise<void>>;
      setCurrentUser: jasmine.Spy<(user: AuthUser | null) => void>;
      logout: jasmine.Spy<() => void>;
    };

    TestBed.configureTestingModule({
      providers: [
        AuthStateService,
        { provide: AuthService, useValue: authServiceStub },
      ],
    });

    service = TestBed.inject(AuthStateService);
  });

  afterEach(() => {
    authServiceStub.bootstrapMe.calls.reset();
    authServiceStub.setCurrentUser.calls.reset();
    authServiceStub.logout.calls.reset();
    bootstrapResolve = undefined;
  });

  it('reuses the same initialization promise while bootstrap is in progress', async () => {
    const firstInitialize = service.initialize();
    const secondInitialize = service.initialize();

    expect(authServiceStub.bootstrapMe).toHaveBeenCalledTimes(1);
    expect(secondInitialize).toBe(firstInitialize);
    expect(service.isLoading()).toBeTrue();

    bootstrapResolve?.();
    await firstInitialize;

    expect(service.isLoading()).toBeFalse();
    expect(service.isInitialized()).toBeTrue();

    const resolvedInitialize = service.initialize();
    expect(authServiceStub.bootstrapMe).toHaveBeenCalledTimes(1);
    await resolvedInitialize;

    service.clear();

    bootstrapPromise = new Promise<void>(resolve => {
      bootstrapResolve = resolve;
    });

    const thirdInitialize = service.initialize();
    expect(authServiceStub.bootstrapMe).toHaveBeenCalledTimes(2);

    bootstrapResolve?.();
    await thirdInitialize;
  });
});
