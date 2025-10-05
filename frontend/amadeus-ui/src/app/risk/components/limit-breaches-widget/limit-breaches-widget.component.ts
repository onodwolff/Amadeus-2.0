import { CommonModule, DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { finalize } from 'rxjs';
import { RiskAlert } from '../../../api/models';
import { NotificationService } from '../../../shared/notifications/notification.service';
import { RiskApi } from '../../../api/clients';
import { observeRiskLimitBreaches } from '../../../ws';
import { WsConnectionState, WsService } from '../../../ws.service';

@Component({
  standalone: true,
  selector: 'app-risk-limit-breaches-widget',
  imports: [CommonModule, DatePipe],
  templateUrl: './limit-breaches-widget.component.html',
  styleUrls: ['../risk-alert-widget/risk-alert-widget.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskLimitBreachesWidgetComponent {
  private readonly ws = inject(WsService);
  private readonly api = inject(RiskApi);
  private readonly notifications = inject(NotificationService);

  private readonly stream = observeRiskLimitBreaches(this.ws);
  readonly alerts$ = this.stream.alerts$;
  readonly state$ = this.stream.state$;

  private readonly pendingActions = signal(new Set<string>());
  readonly pendingEntries = computed(() => this.pendingActions());

  acknowledge(alert: RiskAlert): void {
    if (!alert || alert.acknowledged) {
      return;
    }
    const key = this.actionKey(alert.id, 'ack');
    this.setPending(key, true);
    this.api
      .acknowledgeAlert(alert.id)
      .pipe(finalize(() => this.setPending(key, false)))
      .subscribe({
        next: () => {
          this.notifications.success('Limit breach acknowledged.', 'Risk alerts');
        },
        error: () => {
          this.notifications.error('Failed to acknowledge limit breach.', 'Risk alerts');
        },
      });
  }

  isActionPending(alert: RiskAlert, action: 'ack'): boolean {
    return this.pendingEntries().has(this.actionKey(alert.id, action));
  }

  severityLabel(severity: RiskAlert['severity']): string {
    switch (severity) {
      case 'critical':
        return 'Critical';
      case 'high':
        return 'High';
      case 'medium':
        return 'Medium';
      case 'low':
      default:
        return 'Low';
    }
  }

  connectionLabel(state: WsConnectionState | null | undefined): string {
    switch (state) {
      case 'connected':
        return 'Live';
      case 'disconnected':
        return 'Disconnected';
      default:
        return 'Connecting';
    }
  }

  connectionClass(state: WsConnectionState | null | undefined): string {
    const actual = state ?? 'connecting';
    return `risk-alert-widget__status--${actual}`;
  }

  contextEntries(alert: RiskAlert | null | undefined): Array<{ key: string; value: string }> {
    if (!alert || !alert.context) {
      return [];
    }
    return Object.entries(alert.context)
      .map(([key, value]) => ({ key, value: this.formatContextValue(value) }))
      .filter((entry) => entry.value.length > 0);
  }

  private formatContextValue(value: unknown): string {
    if (value === null || value === undefined) {
      return '';
    }
    if (typeof value === 'number') {
      return value.toString();
    }
    if (typeof value === 'string') {
      return value;
    }
    return JSON.stringify(value);
  }

  private actionKey(id: string, action: string): string {
    return `${id}:${action}`;
  }

  private setPending(key: string, pending: boolean): void {
    this.pendingActions.update((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(key);
      } else {
        next.delete(key);
      }
      return next;
    });
  }
}
