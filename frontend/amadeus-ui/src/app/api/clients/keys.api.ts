import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { ApiKeysResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class KeysApi {
  private readonly http = inject(HttpClient);

  listKeys(): Observable<ApiKeysResponse> {
    return this.http.get<ApiKeysResponse>(buildApiUrl('/keys'));
  }
}
