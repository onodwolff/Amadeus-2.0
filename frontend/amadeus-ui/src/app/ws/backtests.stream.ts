import { map, Observable } from 'rxjs';
import { BacktestRunProgressMessage } from '../api/models';
import { WsService, WsConnectionState } from '../ws.service';

export interface BacktestRunProgressObservables {
  readonly progress$: Observable<BacktestRunProgressMessage>;
  readonly state$: Observable<WsConnectionState>;
}

export function observeBacktestRunProgress(
  runId: string,
  ws: WsService,
): BacktestRunProgressObservables {
  const channel = ws.channel<BacktestRunProgressMessage>({
    name: `backtest-run-${runId}`,
    path: `/ws/backtests/${encodeURIComponent(runId)}/progress`,
    retryAttempts: Infinity,
    retryDelay: 1000,
  });

  const progress$ = channel.messages$.pipe(
    map((message) => (message ?? {})),
  );

  return {
    progress$,
    state$: channel.state$,
  };
}
