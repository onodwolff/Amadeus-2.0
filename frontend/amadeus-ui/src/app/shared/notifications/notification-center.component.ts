import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { NotificationMessage, NotificationService, NotificationType } from './notification.service';

@Component({
  standalone: true,
  selector: 'app-notification-center',
  imports: [CommonModule],
  templateUrl: './notification-center.component.html',
  styleUrls: ['./notification-center.component.scss'],
})
export class NotificationCenterComponent {
  private readonly service = inject(NotificationService);

  readonly notifications = this.service.notifications;
  readonly hasNotifications = computed(() => this.notifications().length > 0);

  trackById(_index: number, item: NotificationMessage): string {
    return item.id;
  }

  dismiss(id: string): void {
    this.service.dismiss(id);
  }

  iconFor(type: NotificationType): string {
    switch (type) {
      case 'success':
        return '✓';
      case 'error':
        return '!';
      case 'warning':
        return '⚠';
      default:
        return 'ℹ';
    }
  }

  ariaLiveFor(type: NotificationType): 'polite' | 'assertive' {
    return type === 'error' || type === 'warning' ? 'assertive' : 'polite';
  }
}
