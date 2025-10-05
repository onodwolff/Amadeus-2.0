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

export interface BacktestRunSummaryDto {
  id: string;
  name: string;
  status: string;
  createdAt: string;
}

export interface BacktestRunResponse {
  run: BacktestRunSummaryDto;
}
