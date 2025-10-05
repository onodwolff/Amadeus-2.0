export type RiskAlertCategory = 'limit_breach' | 'circuit_breaker' | 'margin_call';

export type RiskAlertSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface RiskAlert {
  id: string;
  category: RiskAlertCategory;
  title: string;
  message: string;
  severity: RiskAlertSeverity;
  timestamp: string;
  context?: Record<string, unknown> | null;
  acknowledged: boolean;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  unlockable?: boolean;
  locked?: boolean;
  escalatable?: boolean;
  escalated?: boolean;
  escalated_at?: string | null;
  resolved?: boolean;
  resolved_at?: string | null;
  resolved_by?: string | null;
}

export interface RiskAlertStreamMessage {
  events: RiskAlert[];
  timestamp: string;
}
