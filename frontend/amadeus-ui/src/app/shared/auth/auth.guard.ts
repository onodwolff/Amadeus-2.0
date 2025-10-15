import { Injectable, inject } from '@angular/core';
import { CanActivate, CanActivateChild, UrlTree } from '@angular/router';

import { AuthStateService } from './auth-state.service';
import { AuthService } from '../../auth/auth.service';

@Injectable({ providedIn: 'root' })
export class AuthGuard implements CanActivate, CanActivateChild {
  private readonly authState = inject(AuthStateService);
  private readonly auth = inject(AuthService);

  canActivate(): Promise<boolean | UrlTree> {
    return this.resolve();
  }

  canActivateChild(): Promise<boolean | UrlTree> {
    return this.resolve();
  }

  private async resolve(): Promise<boolean | UrlTree> {
    if (!this.authState.isInitialized()) {
      await this.authState.initialize();
    }

    if (this.authState.currentUser()) {
      return true;
    }

    this.auth.login();
    return false;
  }
}
