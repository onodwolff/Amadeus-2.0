import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { InstrumentsResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class MarketApi {
  private readonly http = inject(HttpClient);

  listInstruments(venue?: string): Observable<InstrumentsResponse> {
    const query = venue ? `?venue=${encodeURIComponent(venue)}` : '';
    return this.http.get<InstrumentsResponse>(buildApiUrl(`/market/instruments${query}`));
  }
}
