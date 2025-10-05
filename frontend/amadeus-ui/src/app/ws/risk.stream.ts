import { map, Observable } from 'rxjs';
import { RiskAlert, RiskAlertStreamMessage } from '../api/models';
import { WsConnectionState, WsService } from '../ws.service';

export interface RiskAlertsStreamObservables {
  readonly alerts$: Observable<RiskAlert[]>;
  readonly state$: Observable<WsConnectionState>;
}

function observeRiskAlertsStream(
  channelName: string,
  path: string,
  ws: WsService,
): RiskAlertsStreamObservables {
  const channel = ws.channel<RiskAlertStreamMessage>({
    name: channelName,
    path,
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  const alerts$ = channel.messages$.pipe(
    map((message) => (Array.isArray(message?.events) ? message.events : [])),
  );

  return {
    alerts$,
    state$: channel.state$,
  };
}

export function observeRiskLimitBreaches(ws: WsService): RiskAlertsStreamObservables {
  return observeRiskAlertsStream('risk-limit-breaches', '/ws/risk/limit-breaches', ws);
}

export function observeRiskCircuitBreakers(ws: WsService): RiskAlertsStreamObservables {
  return observeRiskAlertsStream('risk-circuit-breakers', '/ws/risk/circuit-breakers', ws);
}

export function observeRiskMarginCalls(ws: WsService): RiskAlertsStreamObservables {
  return observeRiskAlertsStream('risk-margin-calls', '/ws/risk/margin-calls', ws);
}
