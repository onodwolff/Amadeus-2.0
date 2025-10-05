import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { InstrumentsResponse, WatchlistRequest, WatchlistResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class MarketApi {
  private readonly http = inject(HttpClient);

  listInstruments(venue?: string): Observable<InstrumentsResponse> {
    const query = venue ? `?venue=${encodeURIComponent(venue)}` : '';
    return this.http.get<InstrumentsResponse>(buildApiUrl(`/market/instruments${query}`));
  }

  getWatchlist(): Observable<WatchlistResponse> {
    return this.http.get<WatchlistResponse>(buildApiUrl('/market/watchlist'));
  }

  updateWatchlist(payload: WatchlistRequest): Observable<WatchlistResponse> {
    return this.http.put<WatchlistResponse>(buildApiUrl('/market/watchlist'), payload);
  }
}
