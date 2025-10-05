import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  HistoricalBarsResponse,
  InstrumentsResponse,
  WatchlistRequest,
  WatchlistResponse,
} from '../models';

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

  getHistoricalBars(
    instrumentId: string,
    granularity: string,
    options?: { limit?: number; start?: string; end?: string },
  ): Observable<HistoricalBarsResponse> {
    let params = new HttpParams().set('granularity', granularity);
    if (options?.limit) {
      params = params.set('limit', options.limit.toString());
    }
    if (options?.start) {
      params = params.set('start', options.start);
    }
    if (options?.end) {
      params = params.set('end', options.end);
    }

    const path = buildApiUrl(
      `/market/instruments/${encodeURIComponent(instrumentId)}/bars`,
    );
    return this.http.get<HistoricalBarsResponse>(path, { params });
  }
}
