import { Injectable, inject } from '@angular/core';
import { MarketTrade } from '../../../api/models';
import { WsChannelHandle, WsService } from '../../../ws.service';

@Injectable({ providedIn: 'root' })
export class TradeTapeDataService {
  private readonly ws = inject(WsService);

  openTradeStream(instrumentId: string): WsChannelHandle<MarketTrade> {
    const params = new URLSearchParams({ instrument: instrumentId });

    return this.ws.channel<MarketTrade>({
      name: `market-trades:${instrumentId}`,
      path: `/ws/market/trades?${params.toString()}`,
    });
  }
}
