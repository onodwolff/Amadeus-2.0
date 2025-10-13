import { inject, Injectable } from '@angular/core';
import { CanActivate, Router, UrlTree } from '@angular/router';

import { AuthStateService } from './auth-state.service';

@Injectable()
export class AdminGuard implements CanActivate {
  private readonly authState = inject(AuthStateService);
  private readonly router = inject(Router);

  async canActivate(): Promise<boolean | UrlTree> {
    await this.authState.initialize();

    if (this.authState.hasAnyPermission(['gateway.users.manage', 'gateway.admin'])) {
      return true;
    }

    return this.router.parseUrl('/403');
  }
}
