import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { ApiKey, ApiKeysResponse, KeyCreateRequest, KeyDeleteRequest, KeyUpdateRequest } from '../models';

@Injectable({ providedIn: 'root' })
export class KeysApi {
  private readonly http = inject(HttpClient);

  listKeys(): Observable<ApiKeysResponse> {
    return this.http.get<ApiKeysResponse>(buildApiUrl('/keys'));
  }

  createKey(payload: KeyCreateRequest): Observable<ApiKey> {
    return this.http.post<ApiKey>(buildApiUrl('/keys'), payload);
  }

  updateKey(keyId: string, payload: KeyUpdateRequest): Observable<ApiKey> {
    return this.http.put<ApiKey>(buildApiUrl(`/keys/${encodeURIComponent(keyId)}`), payload);
  }

  deleteKey(keyId: string, payload: KeyDeleteRequest): Observable<void> {
    return this.http.request<void>('DELETE', buildApiUrl(`/keys/${encodeURIComponent(keyId)}`), {
      body: payload,
    });
  }
}
