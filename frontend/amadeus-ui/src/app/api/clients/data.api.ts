import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { buildApiUrl } from '../../api-base';
import {
  HistoricalDatasetDownloadRequestDto,
  HistoricalDatasetListResponseDto,
  HistoricalDatasetResponseDto,
} from '../models';

@Injectable({ providedIn: 'root' })
export class DataApi {
  private readonly http = inject(HttpClient);

  listDatasets(): Observable<HistoricalDatasetListResponseDto> {
    return this.http.get<HistoricalDatasetListResponseDto>(buildApiUrl('/data/datasets'));
  }

  requestDownload(
    payload: HistoricalDatasetDownloadRequestDto,
  ): Observable<HistoricalDatasetResponseDto> {
    return this.http.post<HistoricalDatasetResponseDto>(buildApiUrl('/data/download'), payload);
  }
}
