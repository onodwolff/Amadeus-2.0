import { Injectable, inject } from '@angular/core';
import { WsChannelHandle, WsService } from '../../../ws.service';

@Injectable({ providedIn: 'root' })
export class OrderBookDataService {
  private readonly ws = inject(WsService);

  openDepthStream(
    instrumentId: string,
    depth: number,
  ): WsChannelHandle {
    const params = new URLSearchParams({
      instrument: instrumentId,
      depth: depth.toString(),
    });

    return this.ws.channel({
      name: `market-depth:${instrumentId}:${depth}`,
      path: `/ws/market/depth?${params.toString()}`,
    });
  }
}
