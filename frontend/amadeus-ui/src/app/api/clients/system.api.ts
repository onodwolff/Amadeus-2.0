import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { CoreInfo, HealthStatus } from '../models';

@Injectable({ providedIn: 'root' })
export class SystemApi {
  private readonly http = inject(HttpClient);

  health(): Observable<HealthStatus> {
    return this.http.get<HealthStatus>(buildApiUrl('/health'));
  }

  coreInfo(): Observable<CoreInfo> {
    return this.http.get<CoreInfo>(buildApiUrl('/core/info'));
  }
}
