import { EncryptedKeySecret } from '../api/models';

const textEncoder = new TextEncoder();
const PBKDF2_ITERATIONS = 100_000;

function toBase64(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  if (typeof btoa === 'function') {
    let binary = '';
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary);
  }

  const nodeBuffer = (globalThis as typeof globalThis & { Buffer?: { from(data: Uint8Array): { toString(encoding: string): string } } }).Buffer;
  if (nodeBuffer) {
    return nodeBuffer.from(bytes).toString('base64');
  }

  throw new Error('Base64 encoding is not supported in this environment.');
}

function toHex(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  return Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

async function deriveAesKey(passphrase: string, salt: Uint8Array): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey('raw', textEncoder.encode(passphrase), 'PBKDF2', false, [
    'deriveKey',
  ]);
  const saltBuffer = new ArrayBuffer(salt.byteLength);
  new Uint8Array(saltBuffer).set(salt);

  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: saltBuffer, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt'],
  );
}

export async function encryptSecret(secret: string, passphrase: string): Promise<EncryptedKeySecret> {
  if (!crypto?.subtle) {
    throw new Error('Web Crypto API is not available in this environment.');
  }

  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveAesKey(passphrase, salt);
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    textEncoder.encode(secret),
  );

  return {
    algorithm: 'AES-GCM',
    ciphertext: toBase64(ciphertext),
    iv: toBase64(iv),
    salt: toBase64(salt),
    iterations: PBKDF2_ITERATIONS,
    kdf: 'PBKDF2',
    hash: 'SHA-256',
  };
}

export async function hashPassphrase(passphrase: string): Promise<string> {
  if (!crypto?.subtle) {
    throw new Error('Web Crypto API is not available in this environment.');
  }

  const digest = await crypto.subtle.digest('SHA-256', textEncoder.encode(passphrase));
  return toHex(digest);
}
