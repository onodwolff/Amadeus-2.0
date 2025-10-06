import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../http';
import { UserResponse, UserUpdateRequest, UsersResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class UsersApi {
  constructor(private readonly http: HttpClient) {}

  listUsers(): Observable<UsersResponse> {
    return this.http.get<UsersResponse>(buildApiUrl('/users'));
  }

  updateUser(userId: string, payload: UserUpdateRequest): Observable<UserResponse> {
    return this.http.put<UserResponse>(buildApiUrl(`/users/${encodeURIComponent(userId)}`), payload);
  }
}
