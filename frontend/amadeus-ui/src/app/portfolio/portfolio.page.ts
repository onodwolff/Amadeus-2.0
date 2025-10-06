import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  Balance,
  CashMovement,
  PortfolioBalancesStreamMessage,
  PortfolioResponse,
  PortfolioSummary,
  PortfolioPositionsStreamMessage,
  PortfolioMovementsStreamMessage,
  Position,
} from '../api/models';
import { PortfolioApi } from '../api/clients/portfolio.api';
import { WsConnectionState, WsService } from '../ws.service';
import {
  observePortfolioBalances,
  observePortfolioMovements,
  observePortfolioPositions,
} from '../ws';
import { PortfolioMetricsPanelComponent } from './components/metrics-panel/portfolio-metrics-panel.component';
import { PortfolioMetricsStore } from './components/metrics-panel/portfolio-metrics.store';
import { PositionSparklineComponent } from './components/position-sparkline/position-sparkline.component';

interface FilterableEntity {
  venue?: string | null;
  account_id?: string | null;
  node_id?: string | null;
}

@Component({
  standalone: true,
  selector: 'app-portfolio-page',
  imports: [CommonModule, FormsModule, PortfolioMetricsPanelComponent, PositionSparklineComponent],
  templateUrl: './portfolio.page.html',
  styleUrls: ['./portfolio.page.scss'],
  providers: [PortfolioMetricsStore],
})
export class PortfolioPage implements OnInit {
  private readonly portfolioApi = inject(PortfolioApi);
  private readonly ws = inject(WsService);
  private readonly metricsStore = inject(PortfolioMetricsStore);

  readonly isLoading = signal(true);
  readonly errorText = signal<string | null>(null);

  readonly summary = signal<PortfolioSummary | null>(null);
  readonly balances = signal<Balance[]>([]);
  readonly positions = signal<Position[]>([]);
  readonly movements = signal<CashMovement[]>([]);
  readonly positionHistory = signal<Record<string, readonly number[]>>({});

  readonly balancesStreamState = signal<WsConnectionState>('connecting');
  readonly positionsStreamState = signal<WsConnectionState>('connecting');
  readonly movementsStreamState = signal<WsConnectionState>('connecting');

  readonly selectedVenue = signal<string | null>(null);
  readonly selectedAccount = signal<string | null>(null);
  readonly selectedNode = signal<string | null>(null);

  ngOnInit(): void {
    this.loadInitial();
    this.observeBalancesStream();
    this.observePositionsStream();
    this.observeMovementsStream();
  }

  readonly availableVenues = computed(() => this.collectOptions('venue'));
  readonly availableAccounts = computed(() => this.collectOptions('account_id'));
  readonly availableNodes = computed(() => this.collectOptions('node_id'));

  readonly filteredBalances = computed(() =>
    this.balances().filter((balance) => this.matchesFilters(balance)),
  );

  readonly filteredPositions = computed(() =>
    this.positions().filter((position) => this.matchesFilters(position)),
  );

  readonly filteredMovements = computed(() =>
    this.movements().filter((movement) => this.matchesFilters(movement)),
  );

  readonly filteredEquity = computed(() =>
    this.filteredBalances().reduce((total, balance) => total + (balance.total ?? 0), 0),
  );

  readonly filteredMargin = computed(() =>
    this.filteredPositions().reduce((total, position) => {
      const margin =
        position.margin_used ??
        Math.abs(position.quantity) * (position.mark_price ?? position.average_price ?? 0) * 0.1;
      return total + margin;
    }, 0),
  );

  readonly lastUpdated = computed(() => this.summary()?.timestamp ?? null);

  readonly hasBalances = computed(() => this.filteredBalances().length > 0);
  readonly hasPositions = computed(() => this.filteredPositions().length > 0);
  readonly hasMovements = computed(() => this.filteredMovements().length > 0);

  positionSparkline(position: Position): readonly number[] {
    const key = this.buildPositionKey(position);
    if (!key) {
      return [];
    }
    const history = this.positionHistory();
    return history[key] ?? [];
  }

  onVenueChange(value: string): void {
    this.selectedVenue.set(value || null);
  }

  onAccountChange(value: string): void {
    this.selectedAccount.set(value || null);
  }

  onNodeChange(value: string): void {
    this.selectedNode.set(value || null);
  }

  private loadInitial(): void {
    this.isLoading.set(true);
    this.errorText.set(null);
    this.portfolioApi.getPortfolio().subscribe({
      next: (response: PortfolioResponse) => {
        const portfolio = response?.portfolio;
        if (!portfolio) {
          this.errorText.set('Portfolio payload is empty.');
          this.isLoading.set(false);
          return;
        }
        this.summary.set(portfolio);
        this.balances.set(portfolio.balances ?? []);
        this.positions.set(portfolio.positions ?? []);
        this.movements.set(portfolio.cash_movements ?? []);
        this.updatePositionHistory(portfolio.positions ?? []);
        this.metricsStore.ingestPositions(
          portfolio.positions ?? [],
          portfolio.timestamp,
          portfolio.equity_value,
        );
        this.isLoading.set(false);
      },
      error: (err) => {
        console.error(err);
        this.errorText.set('Failed to load portfolio data.');
        this.isLoading.set(false);
      },
    });
  }

  private observeBalancesStream(): void {
    const { data$, state$ } = observePortfolioBalances(this.ws);
    state$.pipe(takeUntilDestroyed()).subscribe((state) => this.balancesStreamState.set(state));
    data$.pipe(takeUntilDestroyed()).subscribe({
      next: (payload: PortfolioBalancesStreamMessage) => {
        if (Array.isArray(payload?.balances)) {
          this.balances.set(payload.balances);
        }
        this.patchSummary(payload);
      },
      error: (err) => console.error('Portfolio balances stream error', err),
    });
  }

  private observePositionsStream(): void {
    const { data$, state$ } = observePortfolioPositions(this.ws);
    state$.pipe(takeUntilDestroyed()).subscribe((state) => this.positionsStreamState.set(state));
    data$.pipe(takeUntilDestroyed()).subscribe({
      next: (payload: PortfolioPositionsStreamMessage) => {
        if (Array.isArray(payload?.positions)) {
          this.positions.set(payload.positions);
          this.updatePositionHistory(payload.positions);
          this.metricsStore.ingestPositions(
            payload.positions,
            payload.timestamp,
            payload.equity_value,
          );
        } else if (payload) {
          this.updatePositionHistory(this.positions());
          this.metricsStore.ingestPositions(
            this.positions(),
            payload.timestamp,
            payload.equity_value,
          );
        }
        this.patchSummary(payload);
      },
      error: (err) => console.error('Portfolio positions stream error', err),
    });
  }

  private observeMovementsStream(): void {
    const { data$, state$ } = observePortfolioMovements(this.ws);
    state$.pipe(takeUntilDestroyed()).subscribe((state) => this.movementsStreamState.set(state));
    data$.pipe(takeUntilDestroyed()).subscribe({
      next: (payload: PortfolioMovementsStreamMessage) => {
        if (Array.isArray(payload?.cash_movements)) {
          this.movements.set(payload.cash_movements);
        }
        this.patchSummary(payload);
      },
      error: (err) => console.error('Portfolio movements stream error', err),
    });
  }

  private patchSummary(
    payload:
      | PortfolioBalancesStreamMessage
      | PortfolioPositionsStreamMessage
      | PortfolioMovementsStreamMessage,
  ): void {
    const timestamp = payload?.timestamp ?? this.summary()?.timestamp ?? new Date().toISOString();
    this.summary.update((current) => {
      const next: PortfolioSummary = {
        balances: current?.balances ?? this.balances(),
        positions: current?.positions ?? this.positions(),
        cash_movements: current?.cash_movements ?? this.movements(),
        equity_value: payload?.equity_value ?? current?.equity_value ?? this.filteredEquity(),
        margin_value: payload?.margin_value ?? current?.margin_value ?? this.filteredMargin(),
        timestamp,
      };
      if ('balances' in payload && Array.isArray(payload.balances)) {
        next.balances = payload.balances;
      }
      if ('positions' in payload && Array.isArray(payload.positions)) {
        next.positions = payload.positions;
      }
      if ('cash_movements' in payload && Array.isArray(payload.cash_movements)) {
        next.cash_movements = payload.cash_movements;
      }
      return next;
    });
  }

  private collectOptions(key: keyof FilterableEntity): string[] {
    const values = new Set<string>();
    const append = (entity: FilterableEntity) => {
      const value = entity[key];
      if (value) {
        values.add(value);
      }
    };
    this.balances().forEach(append);
    this.positions().forEach(append);
    this.movements().forEach(append);
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }

  private matchesFilters(entity: FilterableEntity): boolean {
    const venue = this.selectedVenue();
    const account = this.selectedAccount();
    const node = this.selectedNode();

    if (venue && entity.venue !== venue) {
      return false;
    }
    if (account && entity.account_id !== account) {
      return false;
    }
    if (node && entity.node_id !== node) {
      return false;
    }
    return true;
  }

  private updatePositionHistory(positions: readonly Position[] | null | undefined): void {
    if (!positions) {
      return;
    }
    const maxPoints = 180;
    const current = this.positionHistory();
    const next: Record<string, readonly number[]> = { ...current };
    const seen = new Set<string>();

    for (const position of positions) {
      const key = this.buildPositionKey(position);
      if (!key) {
        continue;
      }
      seen.add(key);
      const pnlCandidate = position.unrealized_pnl ?? position.realized_pnl ?? 0;
      const pnl = Number(pnlCandidate);
      if (!Number.isFinite(pnl)) {
        continue;
      }
      const history = next[key] ? [...next[key]] : [];
      history.push(Number(pnl.toFixed(2)));
      next[key] = history.length > maxPoints ? history.slice(-maxPoints) : history;
    }

    for (const key of Object.keys(next)) {
      if (!seen.has(key)) {
        delete next[key];
      }
    }

    const hasChanged =
      Object.keys(current).length !== Object.keys(next).length ||
      Object.entries(next).some(([key, value]) => {
        const existing = current[key];
        if (!existing || existing.length !== value.length) {
          return true;
        }
        for (let index = 0; index < value.length; index += 1) {
          if (existing[index] !== value[index]) {
            return true;
          }
        }
        return false;
      });

    if (hasChanged) {
      this.positionHistory.set(next);
    }
  }

  private buildPositionKey(position: Position | null | undefined): string | null {
    if (!position) {
      return null;
    }
    if (position.position_id) {
      return position.position_id;
    }
    const symbol = position.symbol ?? '';
    const account = position.account_id ?? '';
    const venue = position.venue ?? '';
    const composite = [symbol, account, venue].filter((value) => value).join('::');
    return composite || null;
  }
}
