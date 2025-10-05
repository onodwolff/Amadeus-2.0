import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { catchError, tap, throwError } from 'rxjs';
import { buildApiUrl } from './api-base';

@Injectable({ providedIn: 'root' })
export class ApiService {
  // Base URL is resolved from configuration to avoid cross-origin issues in development.

  constructor(private http: HttpClient) {}

  health() {
    return this.http.get(buildApiUrl('/health')).pipe(
      tap(r => console.log('health:', r)),
      catchError(e => { console.error('health ERR', e); return throwError(() => e); }),
    );
  }

  coreInfo() {
    return this.http.get(buildApiUrl('/core/info')).pipe(
      tap(r => console.log('core:', r)),
      catchError(e => { console.error('core ERR', e); return throwError(() => e); }),
    );
  }

  startBacktest() {
    return this.http.post(buildApiUrl('/nodes/backtest/start'), {}).pipe(
      tap(r => console.log('startBacktest:', r)),
      catchError(e => { console.error('startBacktest ERR', e); return throwError(() => e); }),
    );
  }

  startLive() {
    return this.http.post(buildApiUrl('/nodes/live/start'), {}).pipe(
      tap(r => console.log('startLive:', r)),
      catchError(e => { console.error('startLive ERR', e); return throwError(() => e); }),
    );
  }

  stopNode(id: string) {
    return this.http.post(buildApiUrl(`/nodes/${id}/stop`), {}).pipe(
      tap(r => console.log('stopNode:', id, r)),
      catchError(e => { console.error('stopNode ERR', e); return throwError(() => e); }),
    );
  }

  nodes() {
    return this.http.get(buildApiUrl('/nodes')).pipe(
      tap(r => console.log('nodes:', r)),
      catchError(e => { console.error('nodes ERR', e); return throwError(() => e); }),
    );
  }
}
