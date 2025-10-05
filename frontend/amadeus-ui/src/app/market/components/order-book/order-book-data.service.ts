import { Injectable, inject } from '@angular/core';
import { OrderBookMessage } from '../../../api/models';
import { WsChannelHandle, WsService } from '../../../ws.service';

@Injectable({ providedIn: 'root' })
export class OrderBookDataService {
  private readonly ws = inject(WsService);

  openDepthStream(
    instrumentId: string,
    depth: number,
  ): WsChannelHandle<OrderBookMessage> {
    const params = new URLSearchParams({
      instrument: instrumentId,
      depth: depth.toString(),
    });

    return this.ws.channel<OrderBookMessage>({
      name: `market-depth:${instrumentId}:${depth}`,
      path: `/ws/market/depth?${params.toString()}`,
    });
  }
}
