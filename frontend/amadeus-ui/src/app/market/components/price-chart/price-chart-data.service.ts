import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { MarketApi } from '../../../api/clients/market.api';
import { HistoricalBarsResponse } from '../../../api/models';
import { WsChannelHandle, WsService } from '../../../ws.service';

@Injectable({ providedIn: 'root' })
export class PriceChartDataService {
  private readonly marketApi = inject(MarketApi);
  private readonly ws = inject(WsService);

  loadHistoricalBars(
    instrumentId: string,
    granularity: string,
    options?: { limit?: number; start?: string; end?: string },
  ): Observable<HistoricalBarsResponse> {
    return this.marketApi.getHistoricalBars(instrumentId, granularity, options);
  }

  openTickStream(instrumentId: string): WsChannelHandle {
    return this.ws.channel({
      name: `market-ticks:${instrumentId}`,
      path: `/ws/market/ticks?instrument=${encodeURIComponent(instrumentId)}`,
    });
  }
}
