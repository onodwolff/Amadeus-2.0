import { Injectable } from '@angular/core';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { Subscription } from 'rxjs';
import { buildWebSocketUrl } from './api-base';

interface SubscribeOptions {
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
  retryAttempts?: number;
  retryDelay?: number;
}

@Injectable({ providedIn: 'root' })
export class WsService {
  subscribe(path: string, next: (msg: any) => void, options: SubscribeOptions = {}) {
    const url = path.startsWith('ws') ? path : buildWebSocketUrl(path);
    const maxAttempts = options.retryAttempts ?? 0;
    const baseDelay = options.retryDelay ?? 1000;

    let socket: WebSocketSubject<any> | undefined;
    let subscription: Subscription | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let isStopped = false;

    const clearReconnectTimer = () => {
      if (reconnectTimer !== undefined) {
        clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
    };

    const cleanup = () => {
      subscription?.unsubscribe();
      subscription = undefined;
      socket?.complete();
      socket = undefined;
    };

    const handleDisconnect = (err?: unknown) => {
      if (err !== undefined) {
        console.error(`[ws] error from ${url}`, err);
      } else {
        console.warn(`[ws] connection closed for ${url}`);
      }

      if (!isStopped && (maxAttempts === Infinity || attempt < maxAttempts)) {
        const delay = baseDelay * Math.pow(2, attempt);
        attempt += 1;
        clearReconnectTimer();
        options.onError?.(err ?? new Error('WebSocket disconnected'));
        reconnectTimer = setTimeout(() => {
          reconnectTimer = undefined;
          if (!isStopped) {
            connect();
          }
        }, delay);
      } else {
        options.onClose?.();
      }
    };

    const connect = () => {
      clearReconnectTimer();
      socket = webSocket({
        url,
        openObserver: {
          next: () => {
            attempt = 0;
            options.onOpen?.();
          },
        },
      });

      subscription = socket.subscribe({
        next,
        error: (err) => handleDisconnect(err),
        complete: () => handleDisconnect(),
      });
    };

    connect();

    return () => {
      isStopped = true;
      clearReconnectTimer();
      cleanup();
      options.onClose?.();
    };
  }
}
