import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', loadComponent: () => import('./nodes/nodes.page').then(m => m.NodesPage) },
  { path: 'nodes', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'market', loadComponent: () => import('./market/market.page').then(m => m.MarketPage) },
  { path: 'portfolio', loadComponent: () => import('./portfolio/portfolio.page').then(m => m.PortfolioPage) },
  { path: 'orders', loadComponent: () => import('./orders/orders.page').then(m => m.OrdersPage) },
  {
    path: 'backtest',
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
    loadComponent: () => import('./strategies/strategy-testing.page').then(m => m.StrategyTestingPage),
  },
  { path: 'risk', loadComponent: () => import('./risk/risk.page').then(m => m.RiskPage) },
  {
    path: 'data',
    loadComponent: () => import('./data/historical-data.page').then(m => m.HistoricalDataPage),
  },
  { path: 'settings', loadComponent: () => import('./settings/settings.page').then(m => m.SettingsPage) },
  { path: '**', redirectTo: 'dashboard' },
];
