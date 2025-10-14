import { Injectable, inject, signal } from '@angular/core';
import { HttpErrorResponse, HttpResponse } from '@angular/common/http';
import { OAuthService } from 'angular-oauth2-oidc';
import { firstValueFrom } from 'rxjs';

import { Router } from '@angular/router';

import { AuthApi } from '../api/clients/auth.api';
import { AuthUser, MfaChallengeResponse, OidcCallbackRequest, TokenResponse } from '../api/models';
import { authConfig } from './auth.config';

export interface PasswordLoginCredentials {
  identifier: string;
  password: string;
  captchaToken?: string | null;
  rememberMe?: boolean;
}

export type PasswordLoginResult =
  | { kind: 'authenticated'; user: AuthUser }
  | { kind: 'mfa-required'; challenge: MfaChallengeResponse };

export class PasswordLoginError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'PasswordLoginError';
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly authApi = inject(AuthApi);
  private readonly oauthService = inject(OAuthService);
  private readonly router = inject(Router);

  private readonly currentUserSignal = signal<AuthUser | null>(null);
  private readonly isBootstrappedSignal = signal(false);

  private bootstrapPromise: Promise<void> | null = null;
  private refreshPromise: Promise<void> | null = null;
  private loadUserPromise: Promise<boolean> | null = null;
  private sessionRevision = 0;
  private accessToken: string | null = null;
  private accessTokenExpiresAt = 0;

  readonly currentUser = this.currentUserSignal.asReadonly();
  readonly isBootstrapped = this.isBootstrappedSignal.asReadonly();

  constructor() {
    this.oauthService.configure(authConfig);

    void this.bootstrapMe();
  }

  login(): void {
    this.oauthService.initCodeFlow();
  }

  async loginWithPassword(credentials: PasswordLoginCredentials): Promise<PasswordLoginResult> {
    const identifier = credentials.identifier.trim().toLowerCase();
    const password = credentials.password;
    if (!identifier || !password) {
      throw new PasswordLoginError('Email address or password is missing.');
    }

    try {
      const response = await firstValueFrom(
        this.authApi.loginWithPassword({
          email: identifier,
          password,
          captchaToken: credentials.captchaToken ?? null,
        }),
      );

      return this.handlePasswordLoginResponse(response);
    } catch (error) {
      throw this.normalizePasswordLoginError(error);
    }
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
    this.clearSession();
    this.oauthService.logOut();
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
    return this.hasValidAccessToken() ? this.accessToken : null;
  }

  async refreshToken(): Promise<void> {
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = firstValueFrom(this.authApi.refreshTokens())
      .then(response => {
        this.setSession(response);
      })
      .catch(error => {
        if (this.isAuthenticationError(error)) {
          this.handleRefreshFailure(error);
        } else if ((error as HttpErrorResponse)?.status !== 0) {
          console.error('Token refresh failed.', error);
        }

        throw error;
      })
      .finally(() => {
        this.refreshPromise = null;
      });

    return this.refreshPromise;
  }

  private async initialize(): Promise<void> {
    try {
      await this.oauthService.loadDiscoveryDocument();

      const handledAuthorization = await this.tryProcessAuthorizationCode();
      if (!handledAuthorization) {
        await this.resumeSession();
      }

      if (!this.currentUserSignal() && this.hasValidAccessToken()) {
        await this.loadCurrentUser({ preserveCurrentUser: true });
      }
    } catch (error) {
      console.error('Unable to complete authentication bootstrap.', error);
      this.clearSession();
    } finally {
      this.isBootstrappedSignal.set(true);
    }
  }

  private handlePasswordLoginResponse(
    response: HttpResponse<TokenResponse | MfaChallengeResponse>,
  ): PasswordLoginResult {
    if (response.status === 202) {
      const challenge = response.body as MfaChallengeResponse | null;
      if (!challenge) {
        throw new PasswordLoginError('Multi-factor verification is required, but no challenge was provided.');
      }
      return { kind: 'mfa-required', challenge };
    }

    const tokenResponse = response.body as TokenResponse | null;
    if (!tokenResponse) {
      throw new PasswordLoginError('The authentication server returned an unexpected response.');
    }

    this.setSession(tokenResponse);
    return { kind: 'authenticated', user: tokenResponse.user };
  }

  private normalizePasswordLoginError(error: unknown): PasswordLoginError {
    if (error instanceof PasswordLoginError) {
      return error;
    }

    if (error instanceof HttpErrorResponse) {
      const detail = typeof error.error?.detail === 'string' ? error.error.detail.trim() : null;
      if (error.status === 0) {
        return new PasswordLoginError('Unable to reach the server. Check your network connection and try again.', 0);
      }

      if (detail && detail.length > 0) {
        return new PasswordLoginError(detail, error.status);
      }

      switch (error.status) {
        case 401:
          return new PasswordLoginError('Invalid email or password. Try again.', error.status);
        case 403:
          return new PasswordLoginError(
            'Sign in requires additional verification or your account is suspended. Contact support if this persists.',
            error.status,
          );
        case 429:
          return new PasswordLoginError('Too many attempts. Wait a moment and try again.', error.status);
        case 503:
          return new PasswordLoginError('Sign in is temporarily unavailable. Try again shortly.', error.status);
        default:
          return new PasswordLoginError('Unable to sign in. Try again in a moment.', error.status);
      }
    }

    return new PasswordLoginError('Unable to sign in. Try again in a moment.');
  }

  private async tryProcessAuthorizationCode(): Promise<boolean> {
    if (typeof window === 'undefined') {
      return false;
    }

    const url = new URL(window.location.href);
    const code = url.searchParams.get('code');
    if (!code) {
      return false;
    }

    const codeVerifier = this.getStoredPkceVerifier();
    if (!codeVerifier) {
      console.error('Unable to complete OIDC login. PKCE verifier is missing.');
      this.cleanupAuthorizationArtifacts(url);
      return false;
    }

    try {
      const redirectUri = authConfig.redirectUri ?? window.location.origin ?? '';
      const payload: OidcCallbackRequest = {
        code,
        codeVerifier,
        redirectUri,
      };
      const stateParam = url.searchParams.get('state');
      if (stateParam) {
        payload.state = stateParam;
      }

      const tokenResponse = await firstValueFrom(this.authApi.completeOidcLogin(payload));
      this.setSession(tokenResponse);
      return true;
    } catch (error) {
      if ((error as HttpErrorResponse)?.status !== 0) {
        console.error('Unable to complete OIDC login.', error);
      }
      this.clearSession();
      return false;
    } finally {
      this.cleanupAuthorizationArtifacts(url);
    }
  }

  private async resumeSession(): Promise<void> {
    try {
      const tokenResponse = await firstValueFrom(this.authApi.refreshTokens());
      this.setSession(tokenResponse);
    } catch (error) {
      if (this.isAuthenticationError(error)) {
        this.clearSession();
      } else if ((error as HttpErrorResponse)?.status !== 0) {
        console.error('Unable to resume session.', error);
      }
    }
  }

  private setSession(tokenResponse: TokenResponse): void {
    const wasAuthenticated = this.currentUserSignal() !== null;
    const currentUrl = this.router.url ?? '';
    this.accessToken = tokenResponse.accessToken;
    const expiresInSeconds = Math.max(0, tokenResponse.expiresIn - 5);
    this.accessTokenExpiresAt = Date.now() + expiresInSeconds * 1000;
    this.currentUserSignal.set(tokenResponse.user);
    this.isBootstrappedSignal.set(true);

    if (!wasAuthenticated && this.shouldRedirectAfterLogin(currentUrl)) {
      void this.router.navigateByUrl('/dashboard');
    }
  }

  private clearSession(): void {
    this.accessToken = null;
    this.accessTokenExpiresAt = 0;
    this.currentUserSignal.set(null);
  }

  private hasValidAccessToken(): boolean {
    return !!this.accessToken && Date.now() < this.accessTokenExpiresAt;
  }

  private loadCurrentUser(options?: LoadCurrentUserOptions): Promise<boolean> {
    if (this.loadUserPromise) {
      return this.loadUserPromise;
    }

    const revision = this.sessionRevision;

    if (!this.hasValidAccessToken()) {
      this.clearSession();
      return Promise.resolve(false);
    }

    this.loadUserPromise = (async () => {
      try {
        const user = await firstValueFrom(this.authApi.getCurrentUser());
        if (!this.hasValidAccessToken() || revision !== this.sessionRevision) {
          return false;
        }

        this.currentUserSignal.set(user);
        return true;
      } catch (error) {
        if (revision === this.sessionRevision) {
          let propagatedError: unknown | null = null;

          try {
            options?.onFailure?.(error);
          } catch (hookError) {
            propagatedError = hookError;
          }

          if (!options?.preserveCurrentUser || this.isAuthenticationError(error)) {
            this.handleLoadUserFailure(error);
          } else if ((error as HttpErrorResponse)?.status !== 0) {
            console.error('Unable to load current user.', error);
          }

          if (propagatedError) {
            throw propagatedError;
          }
        }

        return false;
      } finally {
        this.loadUserPromise = null;
      }
    })();

    return this.loadUserPromise;
  }

  private isAuthenticationError(error: unknown): boolean {
    const status = (error as HttpErrorResponse)?.status ?? null;
    return status === 401 || status === 403;
  }

  private handleLoadUserFailure(error: unknown): void {
    const status = (error as HttpErrorResponse)?.status ?? null;
    if (status && status !== 0 && status !== 401) {
      console.error('Unable to load current user.', error);
    }

    if (this.isAuthenticationError(error)) {
      this.clearSession();
      void this.router.navigateByUrl('/login');
    }
  }

  private handleRefreshFailure(error: unknown): void {
    const status = (error as HttpErrorResponse)?.status ?? null;
    if (status && status !== 0) {
      console.error('Token refresh failed.', error);
    }

    this.clearSession();
    this.isBootstrappedSignal.set(false);
    this.oauthService.logOut();
    void this.router.navigateByUrl('/login');
  }

  private getStoredPkceVerifier(): string | null {
    if (typeof window === 'undefined') {
      return null;
    }

    try {
      const persisted = window.localStorage?.getItem('PKCE_verifier');
      if (persisted) {
        return persisted;
      }
    } catch {
      /* ignore storage errors */
    }

    try {
      const sessionValue = window.sessionStorage?.getItem('PKCE_verifier');
      if (sessionValue) {
        return sessionValue;
      }
    } catch {
      /* ignore storage errors */
    }

    return null;
  }

  private clearPkceVerifier(): void {
    if (typeof window === 'undefined') {
      return;
    }

    try {
      window.localStorage?.removeItem('PKCE_verifier');
    } catch {
      /* ignore storage errors */
    }

    try {
      window.sessionStorage?.removeItem('PKCE_verifier');
    } catch {
      /* ignore storage errors */
    }
  }

  private cleanupAuthorizationArtifacts(url: URL): void {
    if (typeof window === 'undefined') {
      return;
    }

    this.clearPkceVerifier();

    const params = url.searchParams;
    params.delete('code');
    params.delete('state');
    params.delete('session_state');

    const cleanedQuery = params.toString();
    const newUrl = `${url.origin}${url.pathname}${cleanedQuery ? `?${cleanedQuery}` : ''}${url.hash}`;

    try {
      window.history.replaceState({}, document.title, newUrl);
    } catch {
      window.location.replace(newUrl);
    }
  }

  private shouldRedirectAfterLogin(url: string): boolean {
    if (!url) {
      return true;
    }

    const normalized = url.split('?')[0] ?? '';
    if (normalized === '/' || normalized === '') {
      return true;
    }

    return normalized.startsWith('/login');
  }
}

interface LoadCurrentUserOptions {
  preserveCurrentUser?: boolean;
  onFailure?: (error: unknown) => void;
}
