import { Injectable, computed, inject, signal } from '@angular/core';

import { AuthApi } from '../../api/clients/auth.api';
import { AuthUser } from '../../api/models';

@Injectable({ providedIn: 'root' })
export class AuthStateService {
  private readonly authApi = inject(AuthApi);

  private readonly currentUserSignal = signal<AuthUser | null>(null);
  private readonly isInitializedSignal = signal(false);
  private readonly isLoadingSignal = signal(false);

  readonly currentUser = this.currentUserSignal.asReadonly();
  readonly isAdmin = computed(() => this.currentUserSignal()?.isAdmin ?? false);
  readonly isInitialized = this.isInitializedSignal.asReadonly();
  readonly isLoading = this.isLoadingSignal.asReadonly();

  initialize(): void {
    if (this.isInitializedSignal() || this.isLoadingSignal()) {
      return;
    }

    this.isLoadingSignal.set(true);
    this.authApi.getCurrentUser().subscribe({
      next: (user) => {
        this.currentUserSignal.set(user);
        this.isInitializedSignal.set(true);
        this.isLoadingSignal.set(false);
      },
      error: (error) => {
        const status = (error as { status?: number })?.status ?? null;
        if (status !== 401) {
          console.error('Unable to load current user.', error);
        }
        this.currentUserSignal.set(null);
        this.isInitializedSignal.set(true);
        this.isLoadingSignal.set(false);
      },
    });
  }

  setCurrentUser(user: AuthUser | null): void {
    this.currentUserSignal.set(user);
    this.isInitializedSignal.set(true);
  }

  clear(): void {
    this.currentUserSignal.set(null);
    this.isInitializedSignal.set(false);
    this.isLoadingSignal.set(false);
  }
}
