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

export interface RiskMetrics {
  timestamp: string;
  total_var?: number;
  stress_var?: number;
  exposure_limits?: RiskLimit[];
  exposures?: RiskExposure[];
}

export interface RiskResponse {
  risk: RiskMetrics;
}
