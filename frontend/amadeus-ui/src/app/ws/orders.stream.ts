import { Observable } from 'rxjs';
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

  return {
    data$: channel.messages$,
    state$: channel.state$,
  };
}
