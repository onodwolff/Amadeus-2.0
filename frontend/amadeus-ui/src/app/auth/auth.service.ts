import { inject, Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom, map, Observable, tap } from 'rxjs';

import { buildApiUrl } from '../api-base';
import { AuthApi } from '../api/clients/auth.api';
import { AuthUser } from '../api/models';

interface LoginRequest {
  email: string;
  password: string;
}

interface LoginResponse {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  tokenType: string;
  user: AuthUser;
}

const ACCESS_TOKEN_STORAGE_KEY = 'amadeus.accessToken';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly authApi = inject(AuthApi);

  private readonly currentUserSignal = signal<AuthUser | null>(null);
  private readonly isBootstrappedSignal = signal(false);
  private bootstrapPromise: Promise<void> | null = null;

  readonly currentUser = this.currentUserSignal;
  readonly isBootstrapped = this.isBootstrappedSignal.asReadonly();

  login(payload: LoginRequest): Observable<AuthUser> {
    return this.http.post<LoginResponse>(buildApiUrl('/auth/login'), payload).pipe(
      tap((response) => {
        this.storeAccessToken(response.accessToken);
        this.currentUserSignal.set(response.user);
        this.isBootstrappedSignal.set(true);
      }),
      map((response) => response.user),
    );
  }

  async bootstrapMe(): Promise<void> {
    if (this.bootstrapPromise) {
      return this.bootstrapPromise;
    }

    this.bootstrapPromise = this.loadCurrentUser().finally(() => {
      this.bootstrapPromise = null;
      this.isBootstrappedSignal.set(true);
    });

    return this.bootstrapPromise;
  }

  logout(): void {
    this.clearAccessToken();
    this.currentUserSignal.set(null);
    this.isBootstrappedSignal.set(false);
  }

  setCurrentUser(user: AuthUser | null): void {
    this.currentUserSignal.set(user);
    if (user) {
      this.isBootstrappedSignal.set(true);
    }
  }

  getAccessToken(): string | null {
    if (typeof localStorage === 'undefined') {
      return null;
    }
    return localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
  }

  private async loadCurrentUser(): Promise<void> {
    const token = this.getAccessToken();
    if (!token) {
      this.currentUserSignal.set(null);
      return;
    }

    try {
      const user = await firstValueFrom(this.authApi.getCurrentUser());
      this.currentUserSignal.set(user);
    } catch (error) {
      const status = (error as { status?: number })?.status ?? null;
      if (status !== 401) {
        console.error('Unable to load current user.', error);
      }
      this.clearAccessToken();
      this.currentUserSignal.set(null);
    }
  }

  private storeAccessToken(token: string): void {
    if (typeof localStorage === 'undefined') {
      return;
    }
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
  }

  private clearAccessToken(): void {
    if (typeof localStorage === 'undefined') {
      return;
    }
    localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  }
}
