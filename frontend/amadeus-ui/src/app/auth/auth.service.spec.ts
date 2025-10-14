import { TestBed } from '@angular/core/testing';
import { Subject, throwError } from 'rxjs';
import { OAuthEvent, OAuthService } from 'angular-oauth2-oidc';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';

import { AuthService } from './auth.service';
import { AuthApi } from '../api/clients/auth.api';
import { AuthUser } from '../api/models';

class OAuthServiceStub {
  readonly events = new Subject<OAuthEvent>();
  configure = jasmine.createSpy('configure');
  setupAutomaticSilentRefresh = jasmine.createSpy('setupAutomaticSilentRefresh');
  initCodeFlow = jasmine.createSpy('initCodeFlow');
  loadDiscoveryDocumentAndTryLogin = jasmine
    .createSpy('loadDiscoveryDocumentAndTryLogin')
    .and.resolveTo(undefined);
  hasValidAccessToken = jasmine.createSpy('hasValidAccessToken').and.returnValue(false);
  getAccessToken = jasmine.createSpy('getAccessToken');
  getRefreshToken = jasmine.createSpy('getRefreshToken');
  refreshToken = jasmine.createSpy('refreshToken').and.returnValue(Promise.resolve());
  logOut = jasmine.createSpy('logOut');
}

class AuthApiStub {
  getCurrentUser = jasmine.createSpy('getCurrentUser');
}

describe('AuthService', () => {
  let service: AuthService;
  let oauthService: OAuthServiceStub;
  let authApi: AuthApiStub;
  let router: jasmine.SpyObj<Router>;
  const user: AuthUser = {
    id: 1,
    email: 'example@example.com',
    username: 'example',
    name: null,
    roles: [],
    permissions: [],
    active: true,
    isAdmin: false,
    emailVerified: true,
    mfaEnabled: false,
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
    lastLoginAt: null,
  };

  beforeEach(async () => {
    TestBed.configureTestingModule({
      providers: [
        AuthService,
        { provide: OAuthService, useClass: OAuthServiceStub },
        { provide: AuthApi, useClass: AuthApiStub },
        { provide: Router, useValue: jasmine.createSpyObj<Router>('Router', ['navigateByUrl']) },
      ],
    });

    oauthService = TestBed.inject(OAuthService) as unknown as OAuthServiceStub;
    authApi = TestBed.inject(AuthApi) as unknown as AuthApiStub;
    router = TestBed.inject(Router) as jasmine.SpyObj<Router>;

    service = TestBed.inject(AuthService);
    await service.bootstrapMe();
  });

  it('keeps current user cleared when logout occurs during pending load', async () => {
    const userSubject = new Subject<AuthUser>();

    authApi.getCurrentUser.and.returnValue(userSubject.asObservable());

    oauthService.hasValidAccessToken.and.returnValue(true);
    const loadPromise = (service as unknown as {
      loadCurrentUser: () => Promise<boolean>;
    }).loadCurrentUser();

    service.logout();
    oauthService.hasValidAccessToken.and.returnValue(false);

    userSubject.next(user);
    userSubject.complete();

    const result = await loadPromise;

    expect(result).toBeFalse();
    expect(service.currentUser()).toBeNull();
  });

  describe('refreshToken', () => {
    beforeEach(() => {
      oauthService.getRefreshToken.and.returnValue('refresh-token');
      oauthService.hasValidAccessToken.and.returnValue(true);
      service.setCurrentUser(user);
    });

    it('logs out when the refreshed profile request returns an authentication error', async () => {
      const httpError = new HttpErrorResponse({ status: 401 });
      authApi.getCurrentUser.and.callFake(() => throwError(() => httpError));

      await expectAsync(service.refreshToken()).toBeRejectedWith(httpError);

      expect(oauthService.logOut).toHaveBeenCalled();
      expect(service.currentUser()).toBeNull();
      expect(router.navigateByUrl).toHaveBeenCalledWith('/login');
    });

    it('keeps the current user when the refreshed profile request fails transiently', async () => {
      const httpError = new HttpErrorResponse({ status: 503 });
      authApi.getCurrentUser.and.callFake(() => throwError(() => httpError));

      await expectAsync(service.refreshToken()).toBeResolved();

      expect(oauthService.logOut).not.toHaveBeenCalled();
      expect(service.currentUser()).toEqual(user);
      expect(router.navigateByUrl).not.toHaveBeenCalled();
    });
  });
});
