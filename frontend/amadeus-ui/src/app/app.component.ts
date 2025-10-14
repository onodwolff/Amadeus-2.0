import { Component, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { NotificationCenterComponent } from './shared/notifications/notification-center.component';
import { AuthStateService } from './shared/auth/auth-state.service';
import {
  NavigationCancel,
  NavigationEnd,
  NavigationError,
  NavigationStart,
  Router,
  RouterEvent,
} from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter } from 'rxjs/operators';

type NavLink = {
  label: string;
  route: string;
  icon: string;
  stroke?: boolean;
  requiredRole?: string;
};

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, RouterOutlet, NotificationCenterComponent],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss'],
})
export class AppComponent {
  private readonly authState = inject(AuthStateService);
  private readonly router = inject(Router);

  protected sidebarOpen = false;
  private readonly currentUrl = signal(this.router.url);

  private readonly baseNavLinks: NavLink[] = [
    {
      label: 'Dashboard',
      route: '/dashboard',
      icon: 'M3 3h8v8H3V3zm10 0h8v8h-8V3zM3 13h8v8H3v-8zm10 0h8v8h-8v-8z',
      requiredRole: 'trader',
    },
    {
      label: 'Market',
      route: '/market',
      icon: 'M4 16.5l5.25-6.75L13 13.5l7-9',
      stroke: true,
      requiredRole: 'trader',
    },
    {
      label: 'Portfolio',
      route: '/portfolio',
      icon: 'M4 6h16M4 10h16M4 14h10M4 18h6',
      stroke: true,
      requiredRole: 'trader',
    },
    { label: 'Orders', route: '/orders', icon: 'M5 5h14v4H5V5zm0 6h14v8H5v-8z', requiredRole: 'trader' },
    {
      label: 'Backtest',
      route: '/backtest',
      icon: 'M5 5h14v14H5V5zm7 4v6m-3-3h6',
      stroke: true,
      requiredRole: 'trader',
    },
    {
      label: 'Strategy Testing',
      route: '/strategy-tests',
      icon: 'M6 6h12M6 12h12M6 18h12m-6-12v4m4 6v4m-8-8v8',
      stroke: true,
      requiredRole: 'trader',
    },
    { label: 'Data', route: '/data', icon: 'M4 4h16v4H4V4zm0 6h16v10H4V10z' },
    {
      label: 'Risk',
      route: '/risk',
      icon: 'M12 3 20 7v6c0 5-3.5 9.5-8 10-4.5-.5-8-5-8-10V7l8-4z',
      requiredRole: 'trader',
    },
    { label: 'Settings', route: '/settings', icon: 'M15 7a3 3 0 1 0-5.83-.88L5 9.29V13h2v2h2v2h3.71l1.82-1.82A3 3 0 0 0 15 7z' },
  ];

  protected readonly navLinks = computed(() => {
    const links = this.baseNavLinks.filter((link) => !link.requiredRole || this.authState.hasRole(link.requiredRole));
    const permissions = this.authState.permissions();
    const canAccessUsers = permissions.some((permission) =>
      ['gateway.users.view', 'gateway.users.manage', 'gateway.admin'].includes(permission),
    );

    if (canAccessUsers) {
      links.push({
        label: 'Users',
        route: '/admin/users',
        icon: 'M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4zm0 2c-3.31 0-6 2.24-6 5v1h12v-1c0-2.76-2.69-5-6-5z',
      });
    }

    return links;
  });

  private readonly standaloneRoutePrefixes = ['/login', '/forgot-password', '/reset-password', '/verify-email'];

  protected readonly showStandalonePage = computed(() =>
    this.standaloneRoutePrefixes.some((prefix) => this.currentUrl().startsWith(prefix)),
  );

  protected toggleSidebar(): void {
    this.sidebarOpen = !this.sidebarOpen;
  }

  protected closeSidebar(): void {
    this.sidebarOpen = false;
  }

  constructor() {
    this.authState.initialize();

    const relevantEvents = [NavigationStart, NavigationEnd, NavigationCancel, NavigationError];

    this.router.events
      .pipe(
        filter((event): event is RouterEvent => relevantEvents.some((type) => event instanceof type)),
        takeUntilDestroyed(),
      )
      .subscribe((event) => {
        const pendingUrl = 'urlAfterRedirects' in event && event.urlAfterRedirects ? event.urlAfterRedirects : event.url;
        this.currentUrl.set(pendingUrl);
      });
  }
}
