import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  AccountResponse,
  AccountUpdateRequest,
  UserCreateRequest,
  PasswordUpdateRequest,
  AdminUsersResponse,
  UserResponse,
  UserManagementUpdateRequest,
} from '../models';

@Injectable({ providedIn: 'root' })
export class UsersApi {
  private readonly http = inject(HttpClient);

  listUsers(): Observable<AdminUsersResponse> {
    return this.http.get<AdminUsersResponse>(buildApiUrl('/users'));
  }

  createUser(payload: UserCreateRequest): Observable<UserResponse> {
    return this.http.post<UserResponse>(buildApiUrl('/users'), payload);
  }

  updateUser(userId: string, payload: UserManagementUpdateRequest): Observable<UserResponse> {
    return this.http.put<UserResponse>(buildApiUrl(`/users/${encodeURIComponent(userId)}`), payload);
  }

  getAccount(): Observable<AccountResponse> {
    return this.http.get<AccountResponse>(buildApiUrl('/settings/account'));
  }

  updateAccount(payload: AccountUpdateRequest): Observable<AccountResponse> {
    return this.http.put<AccountResponse>(buildApiUrl('/settings/account'), payload);
  }

  updatePassword(payload: PasswordUpdateRequest): Observable<AccountResponse> {
    return this.http.put<AccountResponse>(buildApiUrl('/settings/password'), payload);
  }
}
