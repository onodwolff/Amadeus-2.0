import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  NodeDetailResponse,
  NodeLaunchRequest,
  NodeLogsResponse,
  NodeResponse,
  NodesListResponse,
} from '../models';

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

  restartNode(nodeId: string): Observable<NodeResponse> {
    return this.http.post<NodeResponse>(buildApiUrl(`/nodes/${nodeId}/restart`), {});
  }

  deleteNode(nodeId: string): Observable<void> {
    return this.http.delete<void>(buildApiUrl(`/nodes/${nodeId}`));
  }

  getNodeDetail(nodeId: string): Observable<NodeDetailResponse> {
    return this.http.get<NodeDetailResponse>(buildApiUrl(`/nodes/${nodeId}`));
  }

  getNodeLogs(nodeId: string): Observable<NodeLogsResponse> {
    return this.http.get<NodeLogsResponse>(buildApiUrl(`/nodes/${nodeId}/logs/entries`));
  }

  downloadNodeLogs(nodeId: string): Observable<Blob> {
    return this.http.get(buildApiUrl(`/nodes/${nodeId}/logs`), {
      responseType: 'blob',
    });
  }
}
