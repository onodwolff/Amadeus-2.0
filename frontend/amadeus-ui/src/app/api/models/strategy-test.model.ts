export type StrategyOptimisationPlan = 'grid' | 'random';
export type StrategyOptimisationDirection = 'maximize' | 'minimize';

export interface StrategyTestRunRequest {
  name: string;
  baseConfig: Record<string, unknown>;
  parameterSpace: Record<string, unknown[]>;
  plan: StrategyOptimisationPlan;
  sampleCount?: number;
  maxParallel?: number;
  optimisationMetric?: string;
  optimisationDirection?: StrategyOptimisationDirection;
  randomSeed?: number | null;
}

export interface StrategyTestResultDto {
  id: string;
  position: number;
  parameters: Record<string, unknown>;
  metrics: Record<string, unknown>;
  optimisationScore?: number | null;
  status: 'pending' | 'running' | 'completed' | 'failed';
  nodeId?: string | null;
  error?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
}

export interface StrategyTestRunDto {
  id: string;
  name: string;
  plan: StrategyOptimisationPlan;
  status: 'pending' | 'running' | 'completed' | 'failed';
  optimisationMetric?: string | null;
  optimisationDirection?: StrategyOptimisationDirection | null;
  totalJobs: number;
  completedJobs: number;
  failedJobs: number;
  runningJobs: number;
  progress: number;
  createdAt: string;
  updatedAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
  error?: string | null;
  bestResult?: StrategyTestResultDto | null;
  results?: StrategyTestResultDto[] | null;
}

export interface StrategyTestRunResponse {
  run: StrategyTestRunDto;
}

export interface StrategyTestRunListResponse {
  runs: StrategyTestRunDto[];
}
