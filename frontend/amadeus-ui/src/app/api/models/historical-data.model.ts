export interface HistoricalDatasetDto {
  id: number;
  datasetId: string;
  venue: string;
  instrument: string;
  timeframe: string;
  start: string;
  end: string;
  status: string;
  source?: string | null;
  path?: string | null;
  rows?: number | null;
  sizeBytes?: number | null;
  error?: string | null;
  createdAt: string;
  completedAt?: string | null;
}

export interface HistoricalDatasetListResponseDto {
  datasets: HistoricalDatasetDto[];
}

export interface HistoricalDatasetResponseDto {
  dataset: HistoricalDatasetDto;
}

export interface HistoricalDatasetDownloadRequestDto {
  venue: string;
  instrument: string;
  timeframe: string;
  start: string;
  end: string;
  label?: string | null;
  source?: string | null;
}
