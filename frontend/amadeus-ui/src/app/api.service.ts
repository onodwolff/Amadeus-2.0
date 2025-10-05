import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { catchError, tap, throwError } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class ApiService {
  // ВЕЗДЕ localhost (а не 127.0.0.1), чтобы исключить кросс-источники
  private api = 'http://localhost:8000';

  constructor(private http: HttpClient) {}

  health() {
    return this.http.get(`${this.api}/health`).pipe(
      tap(r => console.log('health:', r)),
      catchError(e => { console.error('health ERR', e); return throwError(() => e); }),
    );
  }

  coreInfo() {
    return this.http.get(`${this.api}/core/info`).pipe(
      tap(r => console.log('core:', r)),
      catchError(e => { console.error('core ERR', e); return throwError(() => e); }),
    );
  }

  startBacktest() {
    return this.http.post(`${this.api}/nodes/backtest/start`, {}).pipe(
      tap(r => console.log('startBacktest:', r)),
      catchError(e => { console.error('startBacktest ERR', e); return throwError(() => e); }),
    );
  }

  startLive() {
    return this.http.post(`${this.api}/nodes/live/start`, {}).pipe(
      tap(r => console.log('startLive:', r)),
      catchError(e => { console.error('startLive ERR', e); return throwError(() => e); }),
    );
  }

  stopNode(id: string) {
    return this.http.post(`${this.api}/nodes/${id}/stop`, {}).pipe(
      tap(r => console.log('stopNode:', id, r)),
      catchError(e => { console.error('stopNode ERR', e); return throwError(() => e); }),
    );
  }

  nodes() {
    return this.http.get(`${this.api}/nodes`).pipe(
      tap(r => console.log('nodes:', r)),
      catchError(e => { console.error('nodes ERR', e); return throwError(() => e); }),
    );
  }
}
