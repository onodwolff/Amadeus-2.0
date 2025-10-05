import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { BacktestRunCreateRequest, BacktestRunResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class BacktestsApi {
  private readonly http = inject(HttpClient);

  createRun(payload: BacktestRunCreateRequest): Observable<BacktestRunResponse> {
    return this.http.post<BacktestRunResponse>(buildApiUrl('/backtests/runs'), payload);
  }
}
