import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  AuthUser,
  EmailChangeConfirmRequest,
  EmailChangeRequest,
  EmailChangeResponse,
  MfaDisableRequest,
  MfaEnableRequest,
  MfaSetupResponse,
  OperationStatus,
  SessionsRevokeRequest,
} from '../models';

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private readonly http = inject(HttpClient);

  getCurrentUser(): Observable<AuthUser> {
    return this.http.get<AuthUser>(buildApiUrl('/auth/me'));
  }

  requestEmailChange(payload: EmailChangeRequest): Observable<EmailChangeResponse> {
    return this.http.patch<EmailChangeResponse>(buildApiUrl('/auth/me/email'), payload);
  }

  confirmEmailChange(payload: EmailChangeConfirmRequest): Observable<AuthUser> {
    return this.http.post<AuthUser>(buildApiUrl('/auth/me/email/confirm'), payload);
  }

  setupMfa(): Observable<MfaSetupResponse> {
    return this.http.post<MfaSetupResponse>(buildApiUrl('/auth/me/mfa/setup'), {});
  }

  enableMfa(payload: MfaEnableRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(buildApiUrl('/auth/me/mfa/enable'), payload);
  }

  disableMfa(payload: MfaDisableRequest): Observable<OperationStatus> {
    return this.http.request<OperationStatus>('DELETE', buildApiUrl('/auth/me/mfa'), {
      body: payload,
    });
  }

  revokeAllSessions(payload: SessionsRevokeRequest): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(buildApiUrl('/auth/me/sessions/revoke_all'), payload);
  }
}
