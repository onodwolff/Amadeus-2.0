import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { PortfolioResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class PortfolioApi {
  private readonly http = inject(HttpClient);

  getPortfolio(): Observable<PortfolioResponse> {
    return this.http.get<PortfolioResponse>(buildApiUrl('/portfolio'));
  }
}
