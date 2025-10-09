import { Injectable, inject } from '@angular/core';
import { CanActivate, CanActivateChild, Router, UrlTree } from '@angular/router';

import { AuthStateService } from './auth-state.service';

@Injectable({ providedIn: 'root' })
export class AuthGuard implements CanActivate, CanActivateChild {
  private readonly authState = inject(AuthStateService);
  private readonly router = inject(Router);

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

    return this.router.createUrlTree(['/login']);
  }
}
