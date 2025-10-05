import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'nodes', pathMatch: 'full' },
  { path: 'nodes', loadComponent: () => import('./nodes/nodes.page').then(m => m.NodesPage) },
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
  { path: 'risk', loadComponent: () => import('./risk/risk.page').then(m => m.RiskPage) },
  { path: 'keys', loadComponent: () => import('./keys/keys.page').then(m => m.KeysPage) },
  { path: '**', redirectTo: 'nodes' },
];
