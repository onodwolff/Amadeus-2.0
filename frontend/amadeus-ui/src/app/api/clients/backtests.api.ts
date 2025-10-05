import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  BacktestRunCreateRequest,
  BacktestRunDetailResponse,
  BacktestRunResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class BacktestsApi {
  private readonly http = inject(HttpClient);

  createRun(payload: BacktestRunCreateRequest): Observable<BacktestRunResponse> {
    return this.http.post<BacktestRunResponse>(buildApiUrl('/backtests/runs'), payload);
  }

  getRun(runId: string): Observable<BacktestRunDetailResponse> {
    return this.http.get<BacktestRunDetailResponse>(
      buildApiUrl(`/backtests/runs/${encodeURIComponent(runId)}`),
    );
  }

  downloadReport(runId: string): Observable<Blob> {
    return this.http.get(buildApiUrl(`/backtests/runs/${encodeURIComponent(runId)}/report`), {
      responseType: 'blob',
    });
  }

  exportTrades(runId: string): Observable<Blob> {
    return this.http.get(buildApiUrl(`/backtests/runs/${encodeURIComponent(runId)}/trades`), {
      responseType: 'blob',
    });
  }

  archiveRun(runId: string): Observable<void> {
    return this.http.post<void>(
      buildApiUrl(`/backtests/runs/${encodeURIComponent(runId)}/archive`),
      {},
    );
  }
}
