export type KeyScope = 'trade' | 'read' | 'withdraw' | string;

export interface ApiKey {
  key_id: string;
  venue: string;
  label?: string;
  scopes: KeyScope[];
  created_at: string;
  last_used_at?: string;
  fingerprint?: string;
}

export interface ApiKeysResponse {
  keys: ApiKey[];
}
