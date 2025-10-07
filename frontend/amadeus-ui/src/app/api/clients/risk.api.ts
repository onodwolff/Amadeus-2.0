import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { RiskAlert, RiskLimits, RiskLimitsResponse, RiskResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class RiskApi {
  private readonly http = inject(HttpClient);

  getRisk(): Observable<RiskResponse> {
    return this.http.get<RiskResponse>(buildApiUrl('/api/risk'));
  }

  getRiskLimits(nodeId?: string): Observable<RiskLimitsResponse> {
    let params = new HttpParams();
    if (nodeId) {
      params = params.set('nodeId', nodeId);
    }
    return this.http.get<RiskLimitsResponse>(buildApiUrl('/api/risk/limits'), { params });
  }

  updateRiskLimits(payload: RiskLimits, nodeId?: string): Observable<RiskLimitsResponse> {
    let params = new HttpParams();
    if (nodeId) {
      params = params.set('nodeId', nodeId);
    }
    return this.http.put<RiskLimitsResponse>(buildApiUrl('/api/risk/limits'), payload, { params });
  }

  acknowledgeAlert(alertId: string): Observable<{ alert: RiskAlert }> {
    return this.http.post<{ alert: RiskAlert }>(
      buildApiUrl(`/api/risk/alerts/${encodeURIComponent(alertId)}/ack`),
      {},
    );
  }

  unlockCircuitBreaker(alertId: string): Observable<{ alert: RiskAlert }> {
    return this.http.post<{ alert: RiskAlert }>(
      buildApiUrl(`/api/risk/alerts/${encodeURIComponent(alertId)}/unlock`),
      {},
    );
  }

  escalateMarginCall(alertId: string): Observable<{ alert: RiskAlert }> {
    return this.http.post<{ alert: RiskAlert }>(
      buildApiUrl(`/api/risk/alerts/${encodeURIComponent(alertId)}/escalate`),
      {},
    );
  }
}
