export interface BacktestStrategyParameterDto {
  key: string;
  value: string;
}

export interface BacktestStrategyConfigDto {
  id: string;
  name: string;
  parameters: BacktestStrategyParameterDto[];
}

export interface BacktestDatasetDto {
  id: string;
  name: string;
  venue: string;
  barInterval: string;
  description: string;
  instrument: string;
  start: string;
  end: string;
  status?: string;
}

export interface BacktestDateRangeDto {
  start: string;
  end: string;
}

export interface BacktestEngineParametersDto {
  initialBalance: number;
  baseCurrency: string;
  slippageBps: number;
  commissionBps: number;
  warmupDays: number;
  engineVersion: string;
}

export interface BacktestRunCreateRequest {
  name: string;
  strategy: BacktestStrategyConfigDto;
  dataset: BacktestDatasetDto;
  dateRange: BacktestDateRangeDto;
  engine: BacktestEngineParametersDto;
}

export interface BacktestMetricPointDto {
  timestamp: string;
  value: number;
}

export interface BacktestTradeStatDto {
  label: string;
  value: string | number;
  hint?: string;
}

export interface BacktestRunMetricsDto {
  equityCurve: BacktestMetricPointDto[];
  drawdownCurve: BacktestMetricPointDto[];
  tradeStats: BacktestTradeStatDto[];
}

export interface BacktestRunSummaryMetricDto {
  label: string;
  value: string | number;
  hint?: string;
}

export interface BacktestRunSummaryDto {
  id: string;
  name: string;
  status: string;
  createdAt: string;
}

export interface BacktestRunResponse {
  run: BacktestRunSummaryDto;
}

export interface BacktestRunDetailDto {
  id: string;
  name: string;
  status: string;
  createdAt: string;
  updatedAt?: string;
  startedAt?: string;
  completedAt?: string;
  archivedAt?: string | null;
  progress?: number | null;
  progressStage?: string | null;
  metrics?: BacktestRunMetricsDto | null;
  summary?: BacktestRunSummaryMetricDto[] | null;
  strategy?: BacktestStrategyConfigDto | null;
  dataset?: BacktestDatasetDto | null;
  engine?: BacktestEngineParametersDto | null;
}

export interface BacktestRunDetailResponse {
  run: BacktestRunDetailDto;
}

export interface BacktestRunProgressMessage {
  status?: string;
  progress?: number;
  stage?: string;
  metrics?: Partial<BacktestRunMetricsDto> | null;
  summary?: BacktestRunSummaryMetricDto[] | null;
}
