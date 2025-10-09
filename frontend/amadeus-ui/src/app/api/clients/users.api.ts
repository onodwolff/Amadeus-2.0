import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  AccountResponse,
  AccountUpdateRequest,
  UserCreateRequest,
  PasswordUpdateRequest,
  UsersResponse,
  UserResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class UsersApi {
  private readonly http = inject(HttpClient);

  listUsers(): Observable<UsersResponse> {
    return this.http.get<UsersResponse>(buildApiUrl('/users'));
  }

  updateUser(userId: string, payload: AccountUpdateRequest): Observable<UserResponse> {
    return this.http.put<UserResponse>(buildApiUrl(`/users/${encodeURIComponent(userId)}`), payload);
  }

  createUser(payload: UserCreateRequest): Observable<UserResponse> {
    return this.http.post<UserResponse>(buildApiUrl('/users'), payload);
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
