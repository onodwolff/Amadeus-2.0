import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
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
  OperationStatus,
  ResetPasswordRequest,
  SessionsRevokeRequest,
  TokenResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private readonly http = inject(HttpClient);

  getCurrentUser(): Observable<AuthUser> {
    return this.http.get<AuthUser>(buildApiUrl('/api/auth/me'));
  }

  requestEmailChange(payload: EmailChangeRequest): Observable<EmailChangeResponse> {
    return this.http.patch<EmailChangeResponse>(buildApiUrl('/api/auth/me/email'), payload);
  }

  confirmEmailChange(payload: EmailChangeConfirmRequest): Observable<AuthUser> {
    return this.http.post<AuthUser>(buildApiUrl('/api/auth/me/email/confirm'), payload);
  }

  setupMfa(): Observable<MfaSetupResponse> {
    return this.http.post<MfaSetupResponse>(buildApiUrl('/api/auth/me/mfa/setup'), {});
  }

  enableMfa(payload: MfaEnableRequest): Observable<MfaEnableResponse> {
    return this.http.post<MfaEnableResponse>(buildApiUrl('/api/auth/me/mfa/enable'), payload);
  }

  disableMfa(payload: MfaDisableRequest): Observable<OperationStatus> {
    return this.http.request<OperationStatus>('DELETE', buildApiUrl('/api/auth/me/mfa'), {
      body: payload,
    });
  }

  regenerateBackupCodes(payload: MfaBackupCodesRequest): Observable<BackupCodesResponse> {
    return this.http.post<BackupCodesResponse>(buildApiUrl('/api/auth/me/mfa/backup-codes'), payload);
  }

  completeMfaLogin(payload: MfaChallengeRequest): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(buildApiUrl('/api/auth/login/mfa'), payload);
  }

  exchangeMfaChallenge(email: string, password: string): Observable<MfaChallengeResponse> {
    return this.http.post<MfaChallengeResponse>(buildApiUrl('/api/auth/login'), { email, password });
  }

  revokeAllSessions(payload: SessionsRevokeRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(buildApiUrl('/api/auth/me/sessions/revoke_all'), payload);
  }

  requestPasswordReset(payload: ForgotPasswordRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(buildApiUrl('/api/auth/forgot-password'), payload);
  }

  resetPassword(payload: ResetPasswordRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(buildApiUrl('/api/auth/reset-password'), payload);
  }

  verifyEmail(token: string): Observable<OperationStatus> {
    return this.http.get<OperationStatus>(buildApiUrl('/api/auth/verify-email'), {
      params: { token },
    });
  }
}
