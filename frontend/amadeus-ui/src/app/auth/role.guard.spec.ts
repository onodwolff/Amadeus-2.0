import { Component, WritableSignal, signal } from '@angular/core';
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { Route, Router, UrlSegment, UrlTree } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import { RoleGuard } from './role.guard';
import { AuthService } from './auth.service';
import { AuthUser } from '../api/models';

@Component({ template: '' })
class DummyComponent {}

describe('RoleGuard', () => {
  let guard: RoleGuard;
  let auth: jasmine.SpyObj<AuthService>;
  let router: Router;
  let currentUserSignal: WritableSignal<AuthUser | null>;
  let accessToken: string | null;

  beforeEach(() => {
    currentUserSignal = signal<AuthUser | null>(null);
    accessToken = null;

    auth = jasmine.createSpyObj<AuthService>(
      'AuthService',
      ['bootstrapMe', 'getAccessToken'],
      { currentUser: currentUserSignal.asReadonly() },
    );
    auth.bootstrapMe.and.resolveTo();
    auth.getAccessToken.and.callFake(() => accessToken);

    TestBed.configureTestingModule({
      imports: [
        RouterTestingModule.withRoutes([
          {
            path: 'dashboard',
            canMatch: [RoleGuard],
            data: { requiredRoles: ['trader'] },
            component: DummyComponent,
          },
          { path: '403', component: DummyComponent },
        ]),
      ],
      declarations: [DummyComponent],
      providers: [
        RoleGuard,
        { provide: AuthService, useValue: auth },
      ],
    });

    guard = TestBed.inject(RoleGuard);
    router = TestBed.inject(Router);
  });

  it('allows access when no additional requirements are provided', async () => {
    accessToken = 'token';
    const route: Route = {};

    await expectAsync(guard.canMatch(route, [] as UrlSegment[])).toBeResolvedTo(true);
    expect(auth.bootstrapMe).toHaveBeenCalled();
  });

  it('redirects to /login when the user is not authenticated', async () => {
    accessToken = null;

    const route: Route = {
      data: {
        requiredRoles: ['admin'],
      },
    };

    const result = await guard.canMatch(route, [] as UrlSegment[]);

    expect(auth.bootstrapMe).toHaveBeenCalled();
    expect(result instanceof UrlTree).toBeTrue();
    expect(router.serializeUrl(result as UrlTree)).toEqual(router.serializeUrl(router.parseUrl('/login')));
  });

  it('redirects to /403 when the user lacks a required role', async () => {
    accessToken = 'token';
    currentUserSignal.set({
      id: 1,
      email: 'user@example.com',
      username: 'user',
      name: null,
      roles: ['user'],
      permissions: ['read:items'],
      active: true,
      isAdmin: false,
      emailVerified: true,
      mfaEnabled: false,
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
      lastLoginAt: null,
    });

    const route: Route = {
      data: {
        requiredRoles: ['admin'],
      },
    };

    const result = await guard.canMatch(route, [] as UrlSegment[]);

    expect(auth.bootstrapMe).toHaveBeenCalled();
    expect(result instanceof UrlTree).toBeTrue();
    expect(router.serializeUrl(result as UrlTree)).toEqual(router.serializeUrl(router.parseUrl('/403')));
  });

  it('redirects to /403 when the user lacks a required scope', async () => {
    accessToken = 'token';
    currentUserSignal.set({
      id: 1,
      email: 'user@example.com',
      username: 'user',
      name: null,
      roles: ['user'],
      permissions: ['read:items'],
      active: true,
      isAdmin: false,
      emailVerified: true,
      mfaEnabled: false,
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
      lastLoginAt: null,
    });

    const route: Route = {
      data: {
        requiredScopes: ['write:items'],
      },
    };

    const result = await guard.canMatch(route, [] as UrlSegment[]);

    expect(auth.bootstrapMe).toHaveBeenCalled();
    expect(result instanceof UrlTree).toBeTrue();
    expect(router.serializeUrl(result as UrlTree)).toEqual(router.serializeUrl(router.parseUrl('/403')));
  });

  it('allows administrators to access trader routes', async () => {
    accessToken = 'token';
    currentUserSignal.set({
      id: 1,
      email: 'admin@example.com',
      username: 'admin',
      name: null,
      roles: ['viewer'],
      permissions: ['read:items'],
      active: true,
      isAdmin: true,
      emailVerified: true,
      mfaEnabled: false,
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
      lastLoginAt: null,
    });

    const route: Route = {
      data: {
        requiredRoles: ['trader'],
      },
    };

    await expectAsync(guard.canMatch(route, [] as UrlSegment[])).toBeResolvedTo(true);
  });

  it('redirects to /403 when navigating to /dashboard without the trader role', fakeAsync(() => {
    accessToken = 'token';
    currentUserSignal.set({
      id: 1,
      email: 'user@example.com',
      username: 'user',
      name: null,
      roles: ['viewer'],
      permissions: ['read:items'],
      active: true,
      isAdmin: false,
      emailVerified: true,
      mfaEnabled: false,
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
      lastLoginAt: null,
    });

    router.initialNavigation();
    tick();

    let navigationResult: boolean | undefined;
    router.navigateByUrl('/dashboard').then(result => {
      navigationResult = result;
    });

    tick();

    expect(auth.bootstrapMe).toHaveBeenCalled();
    expect(navigationResult).toBeTrue();
    expect(router.url).toBe('/403');
  }));
});
