import { Injectable, inject } from '@angular/core';
import { CanMatch, Route, Router, UrlSegment, UrlTree } from '@angular/router';
import { OAuthService } from 'angular-oauth2-oidc';

import { AuthService } from './auth.service';

@Injectable({ providedIn: 'root' })
export class RoleGuard implements CanMatch {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly oauthService = inject(OAuthService);

  async canMatch(route: Route, _segments: UrlSegment[]): Promise<boolean | UrlTree> {
    await this.auth.bootstrapMe();

    if (!this.oauthService.hasValidAccessToken()) {
      return this.router.parseUrl('/login');
    }

    const requiredRoles = (route.data?.['requiredRoles'] as string[] | undefined) ?? [];
    const requiredScopes = (route.data?.['requiredScopes'] as string[] | undefined) ?? [];

    if (requiredRoles.length === 0 && requiredScopes.length === 0) {
      return true;
    }

    const grantedRoles = this.extractRoles();
    const grantedScopes = this.extractScopes();

    const hasRoles = this.containsAll(grantedRoles, requiredRoles);
    const hasScopes = this.containsAll(grantedScopes, requiredScopes);

    if (hasRoles && hasScopes) {
      return true;
    }

    return this.router.parseUrl('/403');
  }

  private extractRoles(): Set<string> {
    const claims = (this.oauthService.getIdentityClaims() ?? {}) as Record<string, unknown>;
    const roles = new Set<string>();

    const directRoles = claims['roles'];
    if (Array.isArray(directRoles)) {
      directRoles.forEach(role => roles.add(String(role)));
    }

    const realmAccess = claims['realm_access'];
    if (realmAccess && typeof realmAccess === 'object') {
      const realmRoles = (realmAccess as { roles?: unknown }).roles;
      if (Array.isArray(realmRoles)) {
        realmRoles.forEach(role => roles.add(String(role)));
      }
    }

    const resourceAccess = claims['resource_access'];
    if (resourceAccess && typeof resourceAccess === 'object') {
      Object.values(resourceAccess as Record<string, unknown>).forEach(resource => {
        const resourceRoles = (resource as { roles?: unknown }).roles;
        if (Array.isArray(resourceRoles)) {
          resourceRoles.forEach(role => roles.add(String(role)));
        }
      });
    }

    return roles;
  }

  private extractScopes(): Set<string> {
    const scopes = this.oauthService.getGrantedScopes() as unknown;

    if (typeof scopes === 'string') {
      return new Set(scopes.split(' ').filter(Boolean));
    }

    if (Array.isArray(scopes)) {
      return new Set(scopes.map(scope => String(scope)).filter(Boolean));
    }

    return new Set();
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
