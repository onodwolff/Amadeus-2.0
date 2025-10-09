import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { NotificationCenterComponent } from './shared/notifications/notification-center.component';
import { AuthStateService } from './shared/auth/auth-state.service';

type NavLink = {
  label: string;
  route: string;
  icon: string;
  stroke?: boolean;
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

  protected sidebarOpen = false;

  protected navLinks: NavLink[] = [
    { label: 'Dashboard', route: '/dashboard', icon: 'M3 3h8v8H3V3zm10 0h8v8h-8V3zM3 13h8v8H3v-8zm10 0h8v8h-8v-8z' },
    { label: 'Market', route: '/market', icon: 'M4 16.5l5.25-6.75L13 13.5l7-9', stroke: true },
    { label: 'Portfolio', route: '/portfolio', icon: 'M4 6h16M4 10h16M4 14h10M4 18h6', stroke: true },
    { label: 'Orders', route: '/orders', icon: 'M5 5h14v4H5V5zm0 6h14v8H5v-8z' },
    { label: 'Backtest', route: '/backtest', icon: 'M5 5h14v14H5V5zm7 4v6m-3-3h6', stroke: true },
    {
      label: 'Strategy Testing',
      route: '/strategy-tests',
      icon: 'M6 6h12M6 12h12M6 18h12m-6-12v4m4 6v4m-8-8v8',
      stroke: true,
    },
    { label: 'Data', route: '/data', icon: 'M4 4h16v4H4V4zm0 6h16v10H4V10z' },
    { label: 'Risk', route: '/risk', icon: 'M12 3 20 7v6c0 5-3.5 9.5-8 10-4.5-.5-8-5-8-10V7l8-4z' },
    { label: 'Settings', route: '/settings', icon: 'M15 7a3 3 0 1 0-5.83-.88L5 9.29V13h2v2h2v2h3.71l1.82-1.82A3 3 0 0 0 15 7z' },
  ];

  protected toggleSidebar(): void {
    this.sidebarOpen = !this.sidebarOpen;
  }

  protected closeSidebar(): void {
    this.sidebarOpen = false;
  }

  constructor() {
    this.authState.initialize();
  }
}
