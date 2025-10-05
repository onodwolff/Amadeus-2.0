import { Injectable } from '@angular/core';
import { webSocket } from 'rxjs/webSocket';
import { Subscription } from 'rxjs';
import { buildWebSocketUrl } from './api-base';

interface SubscribeOptions {
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
}

@Injectable({ providedIn: 'root' })
export class WsService {
  subscribe(path: string, next: (msg: any) => void, options: SubscribeOptions = {}) {
    const url = path.startsWith('ws') ? path : buildWebSocketUrl(path);
    const socket = webSocket({
      url,
      openObserver: { next: () => options.onOpen?.() },
      closeObserver: { next: () => options.onClose?.() },
    });

    const subscription: Subscription = socket.subscribe({
      next,
      error: (err) => {
        console.error(`[ws] error from ${url}`, err);
        options.onError?.(err);
      },
    });

    return () => {
      subscription.unsubscribe();
      socket.complete();
    };
  }
}
