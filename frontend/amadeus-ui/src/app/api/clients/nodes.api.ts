import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import { NodeLaunchRequest, NodeResponse, NodesListResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class NodesApi {
  private readonly http = inject(HttpClient);

  listNodes(): Observable<NodesListResponse> {
    return this.http.get<NodesListResponse>(buildApiUrl('/nodes'));
  }

  launchNode(payload: NodeLaunchRequest): Observable<NodeResponse> {
    return this.http.post<NodeResponse>(buildApiUrl('/nodes/launch'), payload);
  }

  stopNode(nodeId: string): Observable<NodeResponse> {
    return this.http.post<NodeResponse>(buildApiUrl(`/nodes/${nodeId}/stop`), {});
  }
}
