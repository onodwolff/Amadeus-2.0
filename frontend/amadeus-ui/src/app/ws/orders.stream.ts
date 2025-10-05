import { map, Observable } from 'rxjs';
import { OrdersStreamMessage } from '../api/models';
import { WsConnectionState, WsService } from '../ws.service';

export interface OrdersStreamObservables {
  readonly data$: Observable<OrdersStreamMessage>;
  readonly state$: Observable<WsConnectionState>;
}

export function observeOrdersStream(ws: WsService): OrdersStreamObservables {
  const channel = ws.channel<OrdersStreamMessage>({
    name: 'orders-stream',
    path: '/ws/orders',
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  const data$ = channel.messages$.pipe(
    map((message) => (typeof message === 'object' && message ? message : {} as OrdersStreamMessage)),
  );

  return {
    data$,
    state$: channel.state$,
  };
}
