// src/app/api.service.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private api = 'http://127.0.0.1:8000';
  constructor(private http: HttpClient) {}

  health() { return this.http.get(`${this.api}/health`); }
  coreInfo() { return this.http.get(`${this.api}/core/info`); }
  startBacktest() { return this.http.post(`${this.api}/nodes/backtest/start`, {}); }
  startLive() { return this.http.post(`${this.api}/nodes/live/start`, {}); }
  stopNode(id: string) { return this.http.post(`${this.api}/nodes/${id}/stop`, {}); }
  nodes() { return this.http.get(`${this.api}/nodes`); }
}
