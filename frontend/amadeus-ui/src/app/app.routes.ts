import { Routes } from '@angular/router';

import { AdminGuard } from './shared/auth/admin.guard';
import { AuthGuard } from './shared/auth/auth.guard';
import { RoleGuard } from './auth/role.guard';

export const routes: Routes = [
  { path: 'forgot-password', loadComponent: () => import('./auth/forgot-password.page').then(m => m.ForgotPasswordPage) },
  { path: 'reset-password', loadComponent: () => import('./auth/reset-password.page').then(m => m.ResetPasswordPage) },
  { path: 'verify-email', loadComponent: () => import('./auth/verify-email.page').then(m => m.VerifyEmailPage) },
  { path: 'login', loadComponent: () => import('./auth/login.page').then(m => m.LoginPage) },
  {
    path: '',
    canMatch: [RoleGuard],
    canActivateChild: [AuthGuard],
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        canMatch: [RoleGuard],
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./nodes/nodes.page').then(m => m.NodesPage),
      },
      { path: 'nodes', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'market',
        canMatch: [RoleGuard],
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./market/market.page').then(m => m.MarketPage),
      },
      {
        path: 'portfolio',
        canMatch: [RoleGuard],
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./portfolio/portfolio.page').then(m => m.PortfolioPage),
      },
      {
        path: 'orders',
        canMatch: [RoleGuard],
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./orders/orders.page').then(m => m.OrdersPage),
      },
      {
        path: 'backtest',
        canMatch: [RoleGuard],
        data: { requiredRoles: ['trader'] },
        children: [
          { path: '', loadComponent: () => import('./backtest/backtest.page').then(m => m.BacktestPage) },
          { path: 'runs/:runId', redirectTo: '/backtest/:runId', pathMatch: 'full' },
          {
            path: ':id',
            canMatch: [RoleGuard],
            data: { requiredRoles: ['trader'] },
            loadComponent: () => import('./backtest/run-detail.page').then(m => m.RunDetailPage),
          },
        ],
      },
      {
        path: 'strategy-tests',
        canMatch: [RoleGuard],
        data: { requiredRoles: ['trader'] },
        loadComponent: () => import('./strategies/strategy-testing.page').then(m => m.StrategyTestingPage),
      },
      {
        path: 'risk',
        canMatch: [RoleGuard],
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
