import { Routes } from '@angular/router';

import { AdminGuard } from './shared/auth/admin.guard';
import { AuthGuard } from './shared/auth/auth.guard';
import { RoleGuard } from './auth/role.guard';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./auth/login.page').then(m => m.LoginPage) },
  {
    path: '',
    canMatch: [RoleGuard],
    canActivateChild: [AuthGuard],
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./nodes/nodes.page').then(m => m.NodesPage),
      },
      { path: 'nodes', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'market',
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./market/market.page').then(m => m.MarketPage),
      },
      {
        path: 'portfolio',
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./portfolio/portfolio.page').then(m => m.PortfolioPage),
      },
      {
        path: 'orders',
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./orders/orders.page').then(m => m.OrdersPage),
      },
      {
        path: 'backtest',
        data: { requiredRoles: ['trader'] },
        children: [
          { path: '', loadComponent: () => import('./backtest/backtest.page').then(m => m.BacktestPage) },
          { path: 'runs/:runId', redirectTo: '/backtest/:runId', pathMatch: 'full' },
          {
            path: ':id',
            loadComponent: () => import('./backtest/run-detail.page').then(m => m.RunDetailPage),
          },
        ],
      },
      {
        path: 'strategy-tests',
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./strategies/strategy-testing.page').then(m => m.StrategyTestingPage),
      },
      {
        path: 'risk',
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./risk/risk.page').then(m => m.RiskPage),
      },
      {
        path: 'data',
        loadComponent: () => import('./data/historical-data.page').then(m => m.HistoricalDataPage),
      },
      { path: 'settings', loadComponent: () => import('./settings/settings.page').then(m => m.SettingsPage) },
      { path: '403', loadComponent: () => import('./forbidden/forbidden.page').then(m => m.ForbiddenPage) },
      {
        path: 'admin/users',
        canMatch: [RoleGuard],
        canActivate: [AdminGuard],
        providers: [AdminGuard],
        data: {
          requiredRoles: ['admin'],
        },
        loadComponent: () => import('./admin/users').then(m => m.AdminUsersPage),
      },
      { path: '**', redirectTo: 'dashboard' },
    ],
  },
];
