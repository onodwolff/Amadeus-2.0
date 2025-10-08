import { CommonModule } from '@angular/common';
import {
  Component,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  effect,
  inject,
  signal,
} from '@angular/core';
import { Subscription } from 'rxjs';
import { Instrument, MarketTrade } from '../../../api/models';
import { WsConnectionState } from '../../../ws.service';
import { TradeTapeDataService } from './trade-tape-data.service';

interface TradeRow extends MarketTrade {
  time: string;
}

@Component({
  standalone: true,
  selector: 'app-trade-tape',
  imports: [CommonModule],
  templateUrl: './trade-tape.component.html',
  styleUrls: ['./trade-tape.component.scss'],
})
export class TradeTapeComponent implements OnChanges, OnDestroy {
  @Input() instrument: Instrument | null = null;

  readonly trades = signal<TradeRow[]>([]);
  readonly wsState = signal<WsConnectionState>('disconnected');
  readonly error = signal<string | null>(null);
  readonly pricePrecision = signal(2);
  readonly volumePrecision = signal(4);
  readonly windowOptions = [25, 50, 100];
  private readonly defaultWindow = this.windowOptions[1] ?? this.windowOptions[0] ?? 25;
  readonly selectedWindow = signal<number>(this.defaultWindow);

  private readonly instrumentId = signal<string | null>(null);
  private readonly dataService = inject(TradeTapeDataService);
  private readonly timeFormatter = new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  private messagesSubscription: Subscription | null = null;
  private stateSubscription: Subscription | null = null;

  constructor() {
    effect(() => {
      const instrumentId = this.instrumentId();
      if (instrumentId) {
        this.connect(instrumentId);
      } else {
        this.teardown();
        this.clear();
      }
    });

    effect(() => {
      // Enforce the configured window size when it changes.
      this.selectedWindow();
      this.trimTrades();
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['instrument']) {
      this.pricePrecision.set(this.resolvePriceDecimals(this.instrument));
      this.volumePrecision.set(this.resolveVolumeDecimals(this.instrument));
      this.clear();
      const instrumentId = this.instrument?.instrument_id ?? null;
      this.instrumentId.set(instrumentId);
      this.wsState.set('disconnected');
      this.error.set(null);
    }
  }

  ngOnDestroy(): void {
    this.teardown();
  }

  setWindowSize(value: string): void {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed > 0) {
      this.selectedWindow.set(parsed);
    }
  }

  trackByTrade(_index: number, trade: TradeRow): string {
    return `${trade.timestamp}-${trade.price}-${trade.volume}`;
  }

  private connect(instrumentId: string): void {
    this.teardown();

    const handle = this.dataService.openTradeStream(instrumentId);
    this.stateSubscription = handle.state$.subscribe((state) => this.wsState.set(state));
    this.messagesSubscription = handle.messages$.subscribe({
      next: (trade) => this.handleTrade(trade),
      error: (err) => {
        console.error('[trade-tape] stream error', err);
        this.error.set('Failed to load trades.');
        this.wsState.set('disconnected');
      },
    });
  }

  private teardown(): void {
    if (this.messagesSubscription) {
      this.messagesSubscription.unsubscribe();
      this.messagesSubscription = null;
    }
    if (this.stateSubscription) {
      this.stateSubscription.unsubscribe();
      this.stateSubscription = null;
    }
    this.wsState.set('disconnected');
  }

  private handleTrade(trade: MarketTrade): void {
    const formatted: TradeRow = {
      ...trade,
      time: this.formatTimestamp(trade.timestamp),
    };

    this.trades.update((current) => [formatted, ...current].slice(0, this.selectedWindow()));
    this.error.set(null);
  }

  private clear(): void {
    this.trades.set([]);
  }

  private trimTrades(): void {
    const limit = this.selectedWindow();
    this.trades.update((current) => current.slice(0, limit));
  }

  private resolvePriceDecimals(instrument: Instrument | null): number {
    const tickSize = Number(instrument?.tick_size ?? 0);
    if (Number.isFinite(tickSize) && tickSize > 0) {
      return this.countDecimals(tickSize);
    }
    return 4;
  }

  private resolveVolumeDecimals(instrument: Instrument | null): number {
    const lotSize = Number(instrument?.lot_size ?? 0);
    if (Number.isFinite(lotSize) && lotSize > 0) {
      return Math.max(0, Math.min(6, this.countDecimals(lotSize)));
    }
    return 4;
  }

  private countDecimals(value: number): number {
    if (!Number.isFinite(value)) {
      return 0;
    }
    const text = value.toString();
    if (!text.includes('.')) {
      return 0;
    }
    return text.split('.')[1]?.length ?? 0;
  }

  private formatTimestamp(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return this.timeFormatter.format(date);
  }
}
