import { AuthConfig } from 'angular-oauth2-oidc';

import { environment } from '../../environments/environment';

function resolveRedirectUri(): string {
  if (environment.oauth?.redirectUri) {
    return environment.oauth.redirectUri;
  }

  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }

  return 'http://localhost:4200';
}

export const authConfig: AuthConfig = {
  responseType: 'code',
  disablePKCE: false,
  issuer: environment.oauth?.issuer ?? '',
  clientId: environment.oauth?.clientId ?? '',
  redirectUri: resolveRedirectUri(),
  scope: environment.oauth?.scope ?? 'openid profile email',
};
