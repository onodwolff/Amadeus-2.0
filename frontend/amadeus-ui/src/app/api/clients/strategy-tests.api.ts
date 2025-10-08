import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { buildApiUrl } from '../../api-base';
import {
  StrategyTestRunListResponse,
  StrategyTestRunRequest,
  StrategyTestRunResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class StrategyTestsApi {
  private readonly http = inject(HttpClient);

  createRun(payload: StrategyTestRunRequest): Observable<StrategyTestRunResponse> {
    return this.http.post<StrategyTestRunResponse>(buildApiUrl('/strategy-tests'), payload);
  }

  getRun(runId: string): Observable<StrategyTestRunResponse> {
    return this.http.get<StrategyTestRunResponse>(
      buildApiUrl(`/strategy-tests/${encodeURIComponent(runId)}`),
    );
  }

  listRuns(): Observable<StrategyTestRunListResponse> {
    return this.http.get<StrategyTestRunListResponse>(buildApiUrl('/strategy-tests'));
  }
}
