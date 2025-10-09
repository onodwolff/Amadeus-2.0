import { Injectable, computed, effect, inject, signal } from '@angular/core';

import { AuthUser } from '../../api/models';
import { AuthService } from '../../auth/auth.service';

@Injectable({ providedIn: 'root' })
export class AuthStateService {
  private readonly auth = inject(AuthService);

  private readonly currentUserSignal = signal<AuthUser | null>(null);
  private readonly isInitializedSignal = signal(false);
  private readonly isLoadingSignal = signal(false);

  readonly currentUser = this.currentUserSignal.asReadonly();
  readonly isAdmin = computed(() => this.currentUserSignal()?.isAdmin ?? false);
  readonly isInitialized = this.isInitializedSignal.asReadonly();
  readonly isLoading = this.isLoadingSignal.asReadonly();

  constructor() {
    effect(
      () => {
        const user = this.auth.currentUser();
        this.currentUserSignal.set(user);
      },
      { allowSignalWrites: true },
    );

    effect(
      () => {
        const bootstrapped = this.auth.isBootstrapped();
        if (bootstrapped) {
          this.isInitializedSignal.set(true);
        } else if (!this.isLoadingSignal()) {
          this.isInitializedSignal.set(false);
        }
      },
      { allowSignalWrites: true },
    );
  }

  initialize(): Promise<void> | void {
    if (this.isInitializedSignal() || this.isLoadingSignal()) {
      return;
    }

    this.isLoadingSignal.set(true);
    return this.auth
      .bootstrapMe()
      .finally(() => {
        this.isInitializedSignal.set(true);
        this.isLoadingSignal.set(false);
      });
  }

  setCurrentUser(user: AuthUser | null): void {
    this.auth.setCurrentUser(user);
    this.isInitializedSignal.set(true);
  }

  clear(): void {
    this.isInitializedSignal.set(false);
    this.isLoadingSignal.set(false);
  }

  logout(): void {
    this.auth.logout();
    this.clear();
  }
}
