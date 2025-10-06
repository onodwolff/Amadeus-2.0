import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { ExchangeListResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class IntegrationsApi {
  private readonly http = inject(HttpClient);

  listExchanges(): Observable<ExchangeListResponse> {
    return this.http.get<ExchangeListResponse>(buildApiUrl('/integrations/exchanges'));
  }
}
