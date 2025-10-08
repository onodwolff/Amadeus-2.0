export interface RiskLimit {
  name: string;
  value: number;
  limit?: number;
  unit?: string;
  breached?: boolean;
}

export interface RiskExposure {
  symbol: string;
  venue: string;
  net_exposure: number;
  notional_value?: number;
  currency?: string;
}

export type RiskModuleStatus = 'up_to_date' | 'stale' | 'syncing' | 'error';

export interface PositionLimitConfig {
  venue: string;
  node: string;
  limit: number;
}

export interface PositionLimitsModule {
  enabled: boolean;
  status: RiskModuleStatus;
  limits: PositionLimitConfig[];
}

export interface MaxLossModule {
  enabled: boolean;
  status: RiskModuleStatus;
  daily: number;
  weekly: number;
}

export interface TradeLockConfig {
  venue: string;
  node: string;
  locked: boolean;
  reason?: string | null;
}

export interface TradeLocksModule {
  enabled: boolean;
  status: RiskModuleStatus;
  locks: TradeLockConfig[];
}

export interface RiskEscalationConfig {
  warn_after: number;
  halt_after: number;
  reset_minutes: number;
}

export interface RiskControlsModule {
  halt_on_breach: boolean;
  notify_on_recovery: boolean;
  escalation: RiskEscalationConfig;
}

export interface RiskLimits {
  position_limits: PositionLimitsModule;
  max_loss: MaxLossModule;
  trade_locks: TradeLocksModule;
  controls: RiskControlsModule;
}

export interface RiskLimitScope {
  user_id: string;
  node_id?: string | null;
}

export interface RiskLimitsResponse {
  limits: RiskLimits;
  scope: RiskLimitScope;
}

export interface RiskMetrics {
  timestamp: string;
  total_var?: number;
  stress_var?: number;
  exposure_limits?: RiskLimit[];
  drawdown_limits?: RiskLimit[];
  usage?: RiskLimit[];
  exposures?: RiskExposure[];
}

export interface RiskResponse {
  risk: RiskMetrics;
  limits: RiskLimits;
}
