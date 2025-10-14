import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  AccountUpdateRequest,
  OperationStatus,
  PasswordUpdateRequest,
  PermissionSummary,
  RoleSummary,
  UserCreateRequest,
  UserProfile,
  UserUpdateRequest,
} from '../models';

@Injectable({ providedIn: 'root' })
export class UsersApi {
  private readonly http = inject(HttpClient);

  listUsers(): Observable<UserProfile[]> {
    return this.http.get<UserProfile[]>(buildApiUrl('/api/admin/users'));
  }

  createUser(payload: UserCreateRequest): Observable<UserProfile> {
    return this.http.post<UserProfile>(buildApiUrl('/api/admin/users'), payload);
  }

  updateUser(userId: number, payload: UserUpdateRequest): Observable<UserProfile> {
    return this.http.patch<UserProfile>(buildApiUrl(`/api/admin/users/${encodeURIComponent(String(userId))}`), payload);
  }

  disableUserMfa(userId: number): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(
      buildApiUrl(`/api/admin/users/${encodeURIComponent(String(userId))}/mfa/disable`),
      {},
    );
  }

  revokeUserSessions(userId: number): Observable<OperationStatus> {
    return this.http.post<OperationStatus>(
      buildApiUrl(`/api/admin/users/${encodeURIComponent(String(userId))}/logout`),
      {},
    );
  }

  assignRole(userId: number, role: string): Observable<UserProfile> {
    return this.http.post<UserProfile>(
      buildApiUrl(`/api/admin/users/${encodeURIComponent(String(userId))}/roles/${encodeURIComponent(role)}`),
      {},
    );
  }

  removeRole(userId: number, role: string): Observable<UserProfile> {
    return this.http.delete<UserProfile>(
      buildApiUrl(`/api/admin/users/${encodeURIComponent(String(userId))}/roles/${encodeURIComponent(role)}`),
    );
  }

  listRoles(): Observable<RoleSummary[]> {
    return this.http.get<RoleSummary[]>(buildApiUrl('/api/admin/roles'));
  }

  listPermissions(): Observable<PermissionSummary[]> {
    return this.http.get<PermissionSummary[]>(buildApiUrl('/api/admin/permissions'));
  }

  getAccount(): Observable<UserProfile> {
    return this.http.get<UserProfile>(buildApiUrl('/api/users/me'));
  }

  updateAccount(userId: number, payload: AccountUpdateRequest): Observable<UserProfile> {
    return this.updateUser(userId, payload);
  }

  changePassword(payload: PasswordUpdateRequest): Observable<void> {
    return this.http.patch<void>(buildApiUrl('/api/users/me/password'), payload);
  }

  updatePassword(userId: number, payload: PasswordUpdateRequest): Observable<UserProfile> {
    return this.updateUser(userId, { password: payload.newPassword });
  }
}
