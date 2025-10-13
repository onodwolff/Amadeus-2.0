import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  AuthUser,
  EmailChangeConfirmRequest,
  EmailChangeRequest,
  EmailChangeResponse,
  ForgotPasswordRequest,
  MfaDisableRequest,
  MfaEnableRequest,
  MfaSetupResponse,
  OperationStatus,
  ResetPasswordRequest,
  SessionsRevokeRequest,
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

  enableMfa(payload: MfaEnableRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(buildApiUrl('/api/auth/me/mfa/enable'), payload);
  }

  disableMfa(payload: MfaDisableRequest): Observable<OperationStatus> {
    return this.http.request<OperationStatus>('DELETE', buildApiUrl('/api/auth/me/mfa'), {
      body: payload,
    });
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
