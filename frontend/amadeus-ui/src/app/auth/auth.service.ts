import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { OAuthEvent, OAuthService } from 'angular-oauth2-oidc';
import { HttpErrorResponse } from '@angular/common/http';

import { AuthApi } from '../api/clients/auth.api';
import { AuthUser } from '../api/models';
import { authConfig } from './auth.config';

function isAuthEvent(event: OAuthEvent, ...types: string[]): boolean {
  return types.includes(event.type);
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly destroyRef = inject(DestroyRef);
  private readonly authApi = inject(AuthApi);
  private readonly oauthService = inject(OAuthService);

  private readonly currentUserSignal = signal<AuthUser | null>(null);
  private readonly isBootstrappedSignal = signal(false);

  private bootstrapPromise: Promise<void> | null = null;
  private refreshPromise: Promise<void> | null = null;
  private loadUserPromise: Promise<boolean> | null = null;
  private sessionRevision = 0;

  readonly currentUser = this.currentUserSignal.asReadonly();
  readonly isBootstrapped = this.isBootstrappedSignal.asReadonly();

  constructor() {
    this.oauthService.configure(authConfig);
    this.oauthService.setupAutomaticSilentRefresh();

    this.oauthService.events
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(event => {
        if (isAuthEvent(event, 'token_received')) {
          void this.loadCurrentUser();
        }

        if (
          isAuthEvent(
            event,
            'token_error',
            'token_refresh_error',
            'session_terminated',
            'session_error',
            'logout',
          )
        ) {
          this.handleSessionEnded();
        }
      });

    void this.bootstrapMe();
  }

  login(): void {
    this.oauthService.initCodeFlow();
  }

  async bootstrapMe(): Promise<void> {
    if (this.bootstrapPromise) {
      return this.bootstrapPromise;
    }

    this.bootstrapPromise = this.initialize().finally(() => {
      this.bootstrapPromise = null;
    });

    return this.bootstrapPromise;
  }

  logout(): void {
    this.sessionRevision += 1;
    this.oauthService.logOut();
    this.currentUserSignal.set(null);
    this.isBootstrappedSignal.set(false);
    this.bootstrapPromise = null;
    this.refreshPromise = null;
  }

  setCurrentUser(user: AuthUser | null): void {
    this.currentUserSignal.set(user);
    if (user) {
      this.isBootstrappedSignal.set(true);
    }
  }

  getAccessToken(): string | null {
    const token = this.oauthService.getAccessToken();
    return token || null;
  }

  async refreshToken(): Promise<void> {
    if (!this.oauthService.getRefreshToken()) {
      throw new Error('No refresh token available.');
    }

    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = this.oauthService
      .refreshToken()
      .then(async () => {
        const loaded = await this.loadCurrentUser();
        if (!loaded) {
          throw new Error('Unable to load user profile after token refresh.');
        }
      })
      .catch(error => {
        this.handleRefreshFailure(error);
        throw error;
      })
      .finally(() => {
        this.refreshPromise = null;
      });

    return this.refreshPromise;
  }

  private async initialize(): Promise<void> {
    try {
      await this.oauthService.loadDiscoveryDocumentAndTryLogin();

      if (this.oauthService.hasValidAccessToken()) {
        await this.loadCurrentUser();
      } else {
        this.currentUserSignal.set(null);
      }
    } catch (error) {
      console.error('Unable to complete authentication bootstrap.', error);
      this.currentUserSignal.set(null);
    } finally {
      this.isBootstrappedSignal.set(true);
    }
  }

  private loadCurrentUser(): Promise<boolean> {
    if (this.loadUserPromise) {
      return this.loadUserPromise;
    }

    const revision = this.sessionRevision;

    if (!this.oauthService.hasValidAccessToken()) {
      this.currentUserSignal.set(null);
      return Promise.resolve(false);
    }

    this.loadUserPromise = firstValueFrom(this.authApi.getCurrentUser())
      .then(user => {
        if (!this.oauthService.hasValidAccessToken() || revision !== this.sessionRevision) {
          return false;
        }

        this.currentUserSignal.set(user);
        return true;
      })
      .catch(error => {
        if (revision === this.sessionRevision) {
          this.handleLoadUserFailure(error);
        }
        return false;
      })
      .finally(() => {
        this.loadUserPromise = null;
      });

    return this.loadUserPromise;
  }

  private handleLoadUserFailure(error: unknown): void {
    const status = (error as HttpErrorResponse)?.status ?? null;
    if (status !== 401) {
      console.error('Unable to load current user.', error);
    }

    this.currentUserSignal.set(null);
  }

  private handleRefreshFailure(error: unknown): void {
    const status = (error as HttpErrorResponse)?.status ?? null;
    if (status && status !== 0) {
      console.error('Token refresh failed.', error);
    }

    this.currentUserSignal.set(null);
    this.isBootstrappedSignal.set(false);
    this.oauthService.logOut();
  }

  private handleSessionEnded(): void {
    this.sessionRevision += 1;
    this.currentUserSignal.set(null);
    this.isBootstrappedSignal.set(false);
    this.bootstrapPromise = null;
    this.refreshPromise = null;
  }
}
