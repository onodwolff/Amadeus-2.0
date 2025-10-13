import { Component } from '@angular/core';
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { Route, Router, UrlSegment, UrlTree } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import { OAuthService } from 'angular-oauth2-oidc';

import { RoleGuard } from './role.guard';
import { AuthService } from './auth.service';

@Component({ template: '' })
class DummyComponent {}

describe('RoleGuard', () => {
  let guard: RoleGuard;
  let auth: jasmine.SpyObj<AuthService>;
  let oauth: jasmine.SpyObj<OAuthService>;
  let router: Router;

  beforeEach(() => {
    auth = jasmine.createSpyObj<AuthService>('AuthService', ['bootstrapMe']);
    auth.bootstrapMe.and.resolveTo();

    oauth = jasmine.createSpyObj<OAuthService>('OAuthService', [
      'hasValidAccessToken',
      'getIdentityClaims',
      'getGrantedScopes',
    ]);
    oauth.hasValidAccessToken.and.returnValue(true);
    oauth.getIdentityClaims.and.returnValue({ roles: [] });
    oauth.getGrantedScopes.and.returnValue({} as unknown as object);

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
        { provide: OAuthService, useValue: oauth },
      ],
    });

    guard = TestBed.inject(RoleGuard);
    router = TestBed.inject(Router);
  });

  it('allows access when no additional requirements are provided', async () => {
    const route: Route = {};

    await expectAsync(guard.canMatch(route, [] as UrlSegment[])).toBeResolvedTo(true);
    expect(auth.bootstrapMe).toHaveBeenCalled();
  });

  it('redirects to /403 when the user lacks a required role', async () => {
    oauth.getIdentityClaims.and.returnValue({ roles: ['user'] });

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
    oauth.getGrantedScopes.and.returnValue('read:items' as unknown as object);

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

  it('redirects to /403 when navigating to /dashboard without the trader role', fakeAsync(() => {
    oauth.getIdentityClaims.and.returnValue({ roles: ['viewer'] });

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
