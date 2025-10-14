import { Injectable, inject } from '@angular/core';
import { CanMatch, Route, Router, UrlSegment, UrlTree } from '@angular/router';
import { AuthService } from './auth.service';

@Injectable({ providedIn: 'root' })
export class RoleGuard implements CanMatch {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);

  async canMatch(route: Route, _segments: UrlSegment[]): Promise<boolean | UrlTree> {
    await this.auth.bootstrapMe();

    if (!this.auth.getAccessToken()) {
      return this.router.parseUrl('/login');
    }

    const requiredRoles = (route.data?.['requiredRoles'] as string[] | undefined) ?? [];
    const requiredScopes = (route.data?.['requiredScopes'] as string[] | undefined) ?? [];

    if (requiredRoles.length === 0 && requiredScopes.length === 0) {
      return true;
    }

    const user = this.auth.currentUser();
    if (!user) {
      return this.router.parseUrl('/login');
    }

    const grantedRoles = new Set(user.roles ?? []);
    const grantedScopes = new Set(user.permissions ?? []);

    const hasRoles = this.containsAll(grantedRoles, requiredRoles);
    const hasScopes = this.containsAll(grantedScopes, requiredScopes);

    if (hasRoles && hasScopes) {
      return true;
    }

    return this.router.parseUrl('/403');
  }

  private containsAll(available: Set<string>, required: string[]): boolean {
    if (required.length === 0) {
      return true;
    }

    for (const item of required) {
      if (!available.has(item)) {
        return false;
      }
    }

    return true;
  }
}
