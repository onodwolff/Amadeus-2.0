import { AdapterStatus } from './node.model';

export interface AdapterSummary {
  total: number;
  connected: number;
  items?: AdapterStatus[];
}

export interface HealthStatus {
  status: string;
  env: string;
  adapters?: AdapterSummary;
}

export interface CoreInfo {
  nautilus_version: string;
  available: boolean;
  adapters?: AdapterSummary;
}
