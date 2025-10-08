import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable, Subscription } from 'rxjs';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { buildWebSocketUrl } from './api-base';

export type WsConnectionState = 'connecting' | 'connected' | 'disconnected';

export interface WsChannelConfig {
  /**
   * Logical channel name. Channels with the same name reuse the same underlying connection.
   */
  name: string;
  /**
   * Relative websocket path (e.g. `/ws/nodes`) or an absolute websocket URL.
   */
  path: string;
  /**
   * Number of reconnection attempts before failing the stream. `Infinity` by default.
   */
  retryAttempts?: number;
  /**
   * Base delay in milliseconds for exponential back-off reconnection attempts.
   */
  retryDelay?: number;
}

export interface WsChannelHandle<T = unknown> {
  readonly name: string;
  readonly messages$: Observable<T>;
  readonly state$: Observable<WsConnectionState>;
}

interface ResolvedChannelConfig {
  name: string;
  url: string;
  retryAttempts: number;
  retryDelay: number;
}

interface InternalChannelState<T = unknown> {
  config: ResolvedChannelConfig;
  source$: Observable<T>;
  statusSubject: BehaviorSubject<WsConnectionState>;
  refCount: number;
}

@Injectable({ providedIn: 'root' })
export class WsService {
  private readonly channels = new Map<string, InternalChannelState<any>>();

  channel<T = unknown>(config: WsChannelConfig): WsChannelHandle<T> {
    const resolved = this.resolveConfig(config);
    const existing = this.channels.get(resolved.name) as InternalChannelState<T> | undefined;

    if (existing) {
      if (existing.config.url !== resolved.url) {
        throw new Error(
          `WebSocket channel "${resolved.name}" already exists with a different target URL`,
        );
      }
      return this.createHandle(resolved.name, existing);
    }

    const statusSubject = new BehaviorSubject<WsConnectionState>('connecting');
    const source$ = this.createSourceObservable<T>(resolved, statusSubject);
    const state: InternalChannelState<T> = {
      config: resolved,
      source$,
      statusSubject,
      refCount: 0,
    };

    this.channels.set(resolved.name, state);

    return this.createHandle(resolved.name, state);
  }

  private resolveConfig(config: WsChannelConfig): ResolvedChannelConfig {
    const url = config.path.startsWith('ws') ? config.path : buildWebSocketUrl(config.path);
    const retryAttempts = config.retryAttempts ?? Infinity;
    const retryDelay = config.retryDelay ?? 1000;

    return {
      name: config.name,
      url,
      retryAttempts,
      retryDelay,
    };
  }

  private createSourceObservable<T>(
    config: ResolvedChannelConfig,
    statusSubject: BehaviorSubject<WsConnectionState>,
  ): Observable<T> {
    return new Observable<T>((subscriber) => {
      let socket: WebSocketSubject<T> | undefined;
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

      const scheduleReconnect = (err?: unknown) => {
        cleanup();
        statusSubject.next('disconnected');

        if (
          !isStopped &&
          (config.retryAttempts === Infinity || attempt < config.retryAttempts)
        ) {
          const delay = config.retryDelay * Math.pow(2, attempt);
          attempt += 1;
          clearReconnectTimer();
          if (err !== undefined) {
            console.error(`[ws] error from ${config.url}`, err);
          } else {
            console.warn(`[ws] connection closed for ${config.url}`);
          }
          reconnectTimer = setTimeout(() => {
            reconnectTimer = undefined;
            if (!isStopped) {
              connect();
            }
          }, delay);
        } else if (err !== undefined) {
          subscriber.error(err);
        } else {
          subscriber.complete();
        }
      };

      const connect = () => {
        statusSubject.next('connecting');
        socket = webSocket<T>({
          url: config.url,
          openObserver: {
            next: () => {
              attempt = 0;
              statusSubject.next('connected');
            },
          },
        });

        subscription = socket.subscribe({
          next: (value) => subscriber.next(value),
          error: (err) => scheduleReconnect(err),
          complete: () => scheduleReconnect(),
        });
      };

      connect();

      return () => {
        isStopped = true;
        clearReconnectTimer();
        cleanup();
        statusSubject.next('disconnected');
      };
    });
  }

  private createHandle<T>(name: string, state: InternalChannelState<T>): WsChannelHandle<T> {
    const messages$ = this.createManagedObservable(name, state, state.source$);
    const state$ = this.createManagedObservable(
      name,
      state,
      state.statusSubject.asObservable(),
    );

    return {
      name,
      messages$,
      state$,
    };
  }

  private createManagedObservable<T>(
    name: string,
    state: InternalChannelState<any>,
    source$: Observable<T>,
  ): Observable<T> {
    return new Observable<T>((observer) => {
      state.refCount += 1;
      const subscription = source$.subscribe({
        next: (value) => observer.next(value),
        error: (err) => observer.error(err),
        complete: () => observer.complete(),
      });

      return () => {
        subscription.unsubscribe();
        state.refCount = Math.max(0, state.refCount - 1);
        if (state.refCount === 0) {
          this.disposeChannel(name, state);
        }
      };
    });
  }

  private disposeChannel<T>(name: string, state: InternalChannelState<T>): void {
    const tracked = this.channels.get(name);
    if (tracked !== state) {
      return;
    }

    this.channels.delete(name);
    state.statusSubject.next('disconnected');
    state.statusSubject.complete();
  }
}
