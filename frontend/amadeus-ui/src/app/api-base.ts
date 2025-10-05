import { environment } from '../environments/environment';

const TRAILING_SLASH_REGEX = /\/+$/;

function normalizeBaseUrl(url: string): string {
  if (!url) {
    return '';
  }
  return url.replace(TRAILING_SLASH_REGEX, '');
}

export function getApiBaseUrl(): string {
  const configured = environment.apiBaseUrl?.trim();
  if (configured) {
    return normalizeBaseUrl(configured);
  }

  if (typeof window !== 'undefined' && window.location?.origin) {
    return normalizeBaseUrl(window.location.origin);
  }

  // Fallback for non-browser environments.
  return 'http://localhost:8000';
}

export function buildApiUrl(path: string): string {
  const base = getApiBaseUrl();
  return `${base}${path.startsWith('/') ? '' : '/'}${path}`;
}

export function buildWebSocketUrl(path: string): string {
  const base = getApiBaseUrl();
  const url = new URL(path, base.endsWith('/') ? `${base}/` : `${base}/`);

  if (url.protocol === 'http:') {
    url.protocol = 'ws:';
  } else if (url.protocol === 'https:') {
    url.protocol = 'wss:';
  }

  return url.toString();
}
