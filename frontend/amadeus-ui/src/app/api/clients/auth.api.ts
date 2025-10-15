import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpResponse } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  AuthUser,
  BackupCodesResponse,
  EmailChangeConfirmRequest,
  EmailChangeRequest,
  EmailChangeResponse,
  ForgotPasswordRequest,
  MfaBackupCodesRequest,
  MfaDisableRequest,
  MfaEnableRequest,
  MfaEnableResponse,
  MfaChallengeRequest,
  MfaChallengeResponse,
  MfaSetupResponse,
  OidcCallbackRequest,
  OperationStatus,
  PasswordLoginRequest,
  ResetPasswordRequest,
  SessionsRevokeRequest,
  TokenResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private readonly http = inject(HttpClient);

  private withCredentials<T extends object>(options?: T): T & { withCredentials: true } {
    return { ...(options ?? {}), withCredentials: true } as T & { withCredentials: true };
  }

  getCurrentUser(): Observable<AuthUser> {
    return this.http.get<AuthUser>(buildApiUrl('/api/auth/me'), this.withCredentials());
  }

  requestEmailChange(payload: EmailChangeRequest): Observable<EmailChangeResponse> {
    return this.http.patch<EmailChangeResponse>(
      buildApiUrl('/api/auth/me/email'),
      payload,
      this.withCredentials(),
    );
  }

  confirmEmailChange(payload: EmailChangeConfirmRequest): Observable<AuthUser> {
    return this.http.post<AuthUser>(
      buildApiUrl('/api/auth/me/email/confirm'),
      payload,
      this.withCredentials(),
    );
  }

  setupMfa(): Observable<MfaSetupResponse> {
    return this.http.post<MfaSetupResponse>(
      buildApiUrl('/api/auth/me/mfa/setup'),
      {},
      this.withCredentials(),
    );
  }

  enableMfa(payload: MfaEnableRequest): Observable<MfaEnableResponse> {
    return this.http.post<MfaEnableResponse>(
      buildApiUrl('/api/auth/me/mfa/enable'),
      payload,
      this.withCredentials(),
    );
  }

  disableMfa(payload: MfaDisableRequest): Observable<OperationStatus> {
    return this.http.request<OperationStatus>(
      'DELETE',
      buildApiUrl('/api/auth/me/mfa'),
      this.withCredentials({ body: payload }),
    );
  }

  regenerateBackupCodes(payload: MfaBackupCodesRequest): Observable<BackupCodesResponse> {
    return this.http.post<BackupCodesResponse>(
      buildApiUrl('/api/auth/me/mfa/backup-codes'),
      payload,
      this.withCredentials(),
    );
  }

  loginWithPassword(
    payload: PasswordLoginRequest,
  ): Observable<HttpResponse<TokenResponse | MfaChallengeResponse>> {
    return this.http.post<TokenResponse | MfaChallengeResponse>(
      buildApiUrl('/api/auth/login'),
      payload,
      this.withCredentials({ observe: 'response' as const }),
    );
  }

  completeMfaLogin(payload: MfaChallengeRequest): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(
      buildApiUrl('/api/auth/login/mfa'),
      payload,
      this.withCredentials(),
    );
  }

  completeOidcLogin(payload: OidcCallbackRequest): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(
      buildApiUrl('/api/auth/oidc/callback'),
      payload,
      this.withCredentials(),
    );
  }

  refreshTokens(): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(
      buildApiUrl('/api/auth/refresh'),
      {},
      this.withCredentials(),
    );
  }

  revokeAllSessions(payload: SessionsRevokeRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(
      buildApiUrl('/api/auth/me/sessions/revoke_all'),
      payload,
      this.withCredentials(),
    );
  }

  requestPasswordReset(payload: ForgotPasswordRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(
      buildApiUrl('/api/auth/forgot-password'),
      payload,
      this.withCredentials(),
    );
  }

  resetPassword(payload: ResetPasswordRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(
      buildApiUrl('/api/auth/reset-password'),
      payload,
      this.withCredentials(),
    );
  }

  verifyEmail(token: string): Observable<OperationStatus> {
    return this.http.get<OperationStatus>(
      buildApiUrl('/api/auth/verify-email'),
      this.withCredentials({ params: { token } }),
    );
  }
}
