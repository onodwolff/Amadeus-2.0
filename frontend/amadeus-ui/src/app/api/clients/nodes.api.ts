import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, throwError } from 'rxjs';
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
    const encodedId = encodeURIComponent(nodeId);
    const legacyUrl = buildApiUrl(`/nodes/${encodedId}`);
    const url = buildApiUrl(`/nodes/${encodedId}/delete`);
    return this.http.post<void>(url, {}).pipe(
      catchError((error: unknown) => {
        if (typeof error === 'object' && error !== null && 'status' in error) {
          const status = (error as { status?: number }).status;
          if (status === 404 || status === 405) {
            return this.http.delete<void>(legacyUrl);
          }
        }
        return throwError(() => error);
      }),
    );
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
