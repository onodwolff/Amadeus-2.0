import { Observable } from 'rxjs';
import {
  PortfolioBalancesStreamMessage,
  PortfolioMovementsStreamMessage,
  PortfolioPositionsStreamMessage,
} from '../api/models';
import { WsConnectionState, WsService } from '../ws.service';

export interface PortfolioStreamObservables<T> {
  readonly data$: Observable<T>;
  readonly state$: Observable<WsConnectionState>;
}

export function observePortfolioBalances(
  ws: WsService,
): PortfolioStreamObservables<PortfolioBalancesStreamMessage> {
  const channel = ws.channel<PortfolioBalancesStreamMessage>({
    name: 'portfolio-balances',
    path: '/ws/portfolio/balances',
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  return {
    data$: channel.messages$,
    state$: channel.state$,
  };
}

export function observePortfolioPositions(
  ws: WsService,
): PortfolioStreamObservables<PortfolioPositionsStreamMessage> {
  const channel = ws.channel<PortfolioPositionsStreamMessage>({
    name: 'portfolio-positions',
    path: '/ws/portfolio/positions',
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  return {
    data$: channel.messages$,
    state$: channel.state$,
  };
}

export function observePortfolioMovements(
  ws: WsService,
): PortfolioStreamObservables<PortfolioMovementsStreamMessage> {
  const channel = ws.channel<PortfolioMovementsStreamMessage>({
    name: 'portfolio-movements',
    path: '/ws/portfolio/movements',
    retryAttempts: Infinity,
    retryDelay: 1500,
  });

  return {
    data$: channel.messages$,
    state$: channel.state$,
  };
}
