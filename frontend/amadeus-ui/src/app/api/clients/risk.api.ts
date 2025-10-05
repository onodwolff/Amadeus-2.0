import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { RiskLimits, RiskResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class RiskApi {
  private readonly http = inject(HttpClient);

  getRisk(): Observable<RiskResponse> {
    return this.http.get<RiskResponse>(buildApiUrl('/risk'));
  }

  getRiskLimits(): Observable<{ limits: RiskLimits }> {
    return this.http.get<{ limits: RiskLimits }>(buildApiUrl('/risk/limits'));
  }

  updateRiskLimits(payload: RiskLimits): Observable<{ limits: RiskLimits }> {
    return this.http.post<{ limits: RiskLimits }>(buildApiUrl('/risk/limits'), payload);
  }
}
