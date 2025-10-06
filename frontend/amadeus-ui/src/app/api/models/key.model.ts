export type KeyScope = 'trade' | 'read' | 'withdraw' | string;

export interface EncryptedKeySecret {
  algorithm: 'AES-GCM';
  ciphertext: string;
  iv: string;
  salt: string;
  iterations: number;
  kdf: 'PBKDF2';
  hash: 'SHA-256';
}

export interface ApiKey {
  key_id: string;
  venue: string;
  label?: string;
  scopes: KeyScope[];
  api_key_masked?: string;
  created_at: string;
  last_used_at?: string | null;
  expires_at?: string;
  fingerprint?: string;
  passphrase_hint?: string;
}

export interface ApiKeysResponse {
  keys: ApiKey[];
}

export interface KeyCreateRequest {
  keyId: string;
  venue: string;
  apiKey: string;
  label?: string;
  scopes: KeyScope[];
  secret: EncryptedKeySecret;
  passphraseHint?: string;
  passphraseHash: string;
}

export interface KeyUpdateRequest {
  venue: string;
  label?: string;
  scopes: KeyScope[];
  apiKey?: string;
  secret?: EncryptedKeySecret;
  passphraseHint?: string;
  passphraseHash: string;
}

export interface KeyDeleteRequest {
  passphraseHash: string;
}
