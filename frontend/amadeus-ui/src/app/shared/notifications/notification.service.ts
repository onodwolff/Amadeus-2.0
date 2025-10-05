import { Injectable, signal } from '@angular/core';

export type NotificationType = 'success' | 'error' | 'info' | 'warning';

export interface NotificationMessage {
  id: string;
  type: NotificationType;
  message: string;
  title?: string;
  createdAt: Date;
}

interface NotifyOptions {
  title?: string;
  timeoutMs?: number | null;
}

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly items = signal<NotificationMessage[]>([]);
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();

  readonly notifications = this.items.asReadonly();

  notify(type: NotificationType, message: string, options?: NotifyOptions): string {
    const id = this.generateId();
    const notification: NotificationMessage = {
      id,
      type,
      message,
      title: options?.title,
      createdAt: new Date(),
    };

    this.items.update((current) => [...current, notification]);

    const timeout = options?.timeoutMs;
    if (timeout !== null) {
      const duration = typeof timeout === 'number' ? Math.max(1500, timeout) : 6000;
      const handle = setTimeout(() => this.dismiss(id), duration);
      this.timers.set(id, handle);
    }

    return id;
  }

  success(message: string, title?: string, timeoutMs?: number | null): string {
    return this.notify('success', message, { title, timeoutMs });
  }

  error(message: string, title?: string, timeoutMs?: number | null): string {
    return this.notify('error', message, { title, timeoutMs });
  }

  info(message: string, title?: string, timeoutMs?: number | null): string {
    return this.notify('info', message, { title, timeoutMs });
  }

  warning(message: string, title?: string, timeoutMs?: number | null): string {
    return this.notify('warning', message, { title, timeoutMs });
  }

  dismiss(id: string): void {
    const timer = this.timers.get(id);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(id);
    }
    this.items.update((current) => current.filter((item) => item.id !== id));
  }

  clear(): void {
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.items.set([]);
  }

  private generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }
}
