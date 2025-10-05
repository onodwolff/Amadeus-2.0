import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { RiskResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class RiskApi {
  private readonly http = inject(HttpClient);

  getRisk(): Observable<RiskResponse> {
    return this.http.get<RiskResponse>(buildApiUrl('/risk'));
  }
}
