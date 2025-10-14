import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';

import { AuthApi } from '../api/clients/auth.api';
import { AuthStateService } from '../shared/auth/auth-state.service';
import { NotificationService } from '../shared/notifications/notification.service';
import { AuthUser } from '../api/models';
import { MfaChallengePage } from './mfa-challenge.page';

function createAuthUser(): AuthUser {
  const timestamp = new Date().toISOString();
  return {
    id: 1,
    email: 'user@example.com',
    username: 'user',
    name: 'User',
    roles: ['member'],
    permissions: [],
    active: true,
    isAdmin: false,
    emailVerified: true,
    mfaEnabled: true,
    createdAt: timestamp,
    updatedAt: timestamp,
    lastLoginAt: timestamp,
  };
}

describe('MfaChallengePage', () => {
  let fixture: ComponentFixture<MfaChallengePage>;
  let component: MfaChallengePage;
  let authApi: jasmine.SpyObj<AuthApi>;
  let authState: jasmine.SpyObj<AuthStateService>;
  let router: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    authApi = jasmine.createSpyObj<AuthApi>('AuthApi', ['completeMfaLogin']);
    authApi.completeMfaLogin.and.returnValue(
      of({
        accessToken: 'token',
        tokenType: 'bearer',
        expiresIn: 900,
        refreshExpiresAt: new Date().toISOString(),
        user: createAuthUser(),
      }),
    );

    authState = jasmine.createSpyObj<AuthStateService>('AuthStateService', ['setCurrentUser']);

    const notificationService = jasmine.createSpyObj<NotificationService>(
      'NotificationService',
      ['success', 'info', 'warning', 'error'],
    );

    router = jasmine.createSpyObj<Router>('Router', ['navigateByUrl']);

    await TestBed.configureTestingModule({
      imports: [MfaChallengePage],
      providers: [
        provideZonelessChangeDetection(),
        { provide: AuthApi, useValue: authApi },
        { provide: AuthStateService, useValue: authState },
        { provide: NotificationService, useValue: notificationService },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({
                token: 'challenge-token',
                detail: 'Multi-factor verification required',
              }),
            },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(MfaChallengePage);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('submits the challenge and navigates on success', async () => {
    component['form'].setValue({ code: '123456', rememberDevice: true });
    await component['submit']();
    expect(authApi.completeMfaLogin).toHaveBeenCalledWith({
      challengeToken: 'challenge-token',
      code: '123456',
      rememberDevice: true,
    });
    expect(authState.setCurrentUser).toHaveBeenCalled();
    expect(router.navigateByUrl).toHaveBeenCalledWith('/dashboard');
  });
});
