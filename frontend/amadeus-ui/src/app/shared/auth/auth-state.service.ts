import { Injectable, computed, effect, inject, signal } from '@angular/core';

import { AuthUser } from '../../api/models';
import { AuthService } from '../../auth/auth.service';

@Injectable({ providedIn: 'root' })
export class AuthStateService {
  private readonly auth = inject(AuthService);

  private readonly currentUserSignal = signal<AuthUser | null>(null);
  private readonly isInitializedSignal = signal(false);
  private readonly isLoadingSignal = signal(false);
  private initializationPromise: Promise<void> | null = null;

  readonly currentUser = this.currentUserSignal.asReadonly();
  readonly isAdmin = computed(() => this.currentUserSignal()?.isAdmin ?? false);
  readonly permissions = computed(() => this.currentUserSignal()?.permissions ?? []);
  readonly roles = computed(() => this.currentUserSignal()?.roles ?? []);
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

  initialize(): Promise<void> {
    if (this.isInitializedSignal()) {
      return Promise.resolve();
    }

    if (this.isLoadingSignal()) {
      return this.initializationPromise ?? Promise.resolve();
    }

    if (!this.initializationPromise) {
      this.isLoadingSignal.set(true);
      this.initializationPromise = this.auth.bootstrapMe().finally(() => {
        this.isInitializedSignal.set(true);
        this.isLoadingSignal.set(false);
        this.initializationPromise = null;
      });
    }

    return this.initializationPromise ?? Promise.resolve();
  }

  hasPermission(permission: string): boolean {
    return this.permissions().includes(permission);
  }

  hasAnyPermission(permissions: Iterable<string>): boolean {
    const granted = new Set(this.permissions());
    for (const permission of permissions) {
      if (granted.has(permission)) {
        return true;
      }
    }
    return false;
  }

  hasAllPermissions(permissions: Iterable<string>): boolean {
    const granted = new Set(this.permissions());
    for (const permission of permissions) {
      if (!granted.has(permission)) {
        return false;
      }
    }
    return true;
  }

  hasRole(role: string): boolean {
    return this.roles().includes(role);
  }

  setCurrentUser(user: AuthUser | null): void {
    this.auth.setCurrentUser(user);
    this.isInitializedSignal.set(true);
  }

  clear(): void {
    this.isInitializedSignal.set(false);
    this.isLoadingSignal.set(false);
    this.initializationPromise = null;
  }

  logout(): void {
    this.auth.logout();
    this.clear();
  }
}
