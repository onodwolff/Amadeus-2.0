import { CommonModule } from '@angular/common';
import {
  Component,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { Subscription } from 'rxjs';
import { Instrument, OrderBookMessage } from '../../../api/models';
import { WsConnectionState } from '../../../ws.service';
import { OrderBookDataService } from './order-book-data.service';

interface OrderBookRow {
  price: number;
  size: number;
  total: number;
}

interface InternalOrderBookState {
  bids: Map<number, number>;
  asks: Map<number, number>;
  lastTimestamp: string | null;
}

@Component({
  standalone: true,
  selector: 'app-order-book',
  imports: [CommonModule],
  templateUrl: './order-book.component.html',
  styleUrls: ['./order-book.component.scss'],
})
export class OrderBookComponent implements OnChanges, OnDestroy {
  @Input() instrument: Instrument | null = null;

  readonly depthOptions = [10, 20, 30, 50];
  private readonly aggregationMultipliers = [1, 2, 5, 10];
  private readonly defaultDepth = this.depthOptions[1] ?? this.depthOptions[0] ?? 10;

  readonly instrumentSignal = signal<Instrument | null>(null);
  readonly selectedDepth = signal<number>(this.defaultDepth);
  readonly selectedAggregation = signal(0);
  readonly wsState = signal<WsConnectionState>('disconnected');
  readonly error = signal<string | null>(null);
  readonly lastUpdated = signal<string | null>(null);
  readonly bids = signal<OrderBookRow[]>([]);
  readonly asks = signal<OrderBookRow[]>([]);
  readonly maxBidTotal = signal(0);
  readonly maxAskTotal = signal(0);
  readonly pricePrecision = signal(2);
  readonly hasLevels = computed(() => this.bids().length > 0 || this.asks().length > 0);

  readonly aggregationOptions = computed(() => {
    const instrument = this.instrumentSignal();
    const tickSize = Number(instrument?.tick_size ?? 0);
    const baseStep = Number.isFinite(tickSize) && tickSize > 0 ? tickSize : this.estimateFallbackStep(instrument);

    const options = [
      { value: 0, label: 'Native' },
      ...this.aggregationMultipliers.map((multiplier) => {
        const step = baseStep * multiplier;
        return {
          value: step,
          label: `${multiplier}× ${this.formatPrice(step)}`,
        };
      }),
    ];

    return options;
  });

  private readonly dataService = inject(OrderBookDataService);
  private readonly priceFormatter = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  });
  private readonly timeFormatter = new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  private instrumentId = signal<string | null>(null);
  private messageSubscription: Subscription | null = null;
  private stateSubscription: Subscription | null = null;
  private activeChannelKey: string | null = null;
  private bookState: InternalOrderBookState = {
    bids: new Map<number, number>(),
    asks: new Map<number, number>(),
    lastTimestamp: null,
  };

  constructor() {
    effect(() => {
      // Reconnect when the instrument or requested depth changes.
      const instrumentId = this.instrumentId();
      const depth = this.selectedDepth();
      if (instrumentId) {
        this.connect(instrumentId, depth);
      } else {
        this.teardown();
        this.resetBook();
      }
    });

    effect(() => {
      // Re-render when aggregation changes.
      this.selectedAggregation();
      this.refreshView();
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['instrument']) {
      this.instrumentSignal.set(this.instrument);
      this.pricePrecision.set(this.resolvePriceDecimals(this.instrument));
      this.resetBook();
      const instrumentId = this.instrument?.instrument_id ?? null;
      this.instrumentId.set(instrumentId);

      const aggregation = this.aggregationOptions()[0]?.value ?? 0;
      this.selectedAggregation.set(aggregation);
      this.wsState.set('disconnected');
      this.error.set(null);
    }
  }

  ngOnDestroy(): void {
    this.teardown();
  }

  setDepth(depthValue: string): void {
    const parsed = Number(depthValue);
    if (Number.isFinite(parsed) && parsed > 0) {
      this.selectedDepth.set(parsed);
    }
  }

  setAggregation(stepValue: string): void {
    const parsed = Number(stepValue);
    if (!Number.isNaN(parsed) && parsed >= 0) {
      this.selectedAggregation.set(parsed);
    }
  }

  trackByPrice(_index: number, row: OrderBookRow): number {
    return row.price;
  }

  private connect(instrumentId: string, depth: number): void {
    const channelKey = `${instrumentId}:${depth}`;
    if (this.activeChannelKey === channelKey) {
      this.refreshView();
      return;
    }

    this.teardown();
    this.activeChannelKey = channelKey;

    const handle = this.dataService.openDepthStream(instrumentId, depth);

    this.stateSubscription = handle.state$.subscribe((state) => {
      this.wsState.set(state);
    });

    this.messageSubscription = handle.messages$.subscribe({
      next: (message) => this.handleMessage(message),
      error: (err) => {
        console.error('[order-book] stream error', err);
        this.error.set('Failed to load order book data.');
        this.wsState.set('disconnected');
      },
    });
  }

  private teardown(): void {
    this.activeChannelKey = null;
    this.messageSubscription?.unsubscribe();
    this.messageSubscription = null;
    this.stateSubscription?.unsubscribe();
    this.stateSubscription = null;
    this.wsState.set('disconnected');
  }

  private resetBook(): void {
    this.bookState = {
      bids: new Map<number, number>(),
      asks: new Map<number, number>(),
      lastTimestamp: null,
    };
    this.refreshView();
    this.lastUpdated.set(null);
  }

  private handleMessage(message: OrderBookMessage): void {
    if (message.type === 'snapshot') {
      this.bookState.bids = this.createSideMap(message.bids);
      this.bookState.asks = this.createSideMap(message.asks);
    } else {
      this.updateSideMap(this.bookState.bids, message.bids);
      this.updateSideMap(this.bookState.asks, message.asks);
    }

    this.bookState.lastTimestamp = message.timestamp;
    this.refreshView();
    this.lastUpdated.set(this.formatTimestamp(message.timestamp));
    this.error.set(null);
  }

  private createSideMap(levels: [number, number][]): Map<number, number> {
    const map = new Map<number, number>();
    for (const [price, size] of levels) {
      if (!Number.isFinite(price) || !Number.isFinite(size)) {
        continue;
      }
      if (size <= 0) {
        continue;
      }
      map.set(price, size);
    }
    return map;
  }

  private updateSideMap(target: Map<number, number>, deltas: [number, number][]): void {
    for (const [price, size] of deltas) {
      if (!Number.isFinite(price) || !Number.isFinite(size)) {
        continue;
      }
      if (size <= 0) {
        target.delete(price);
      } else {
        target.set(price, size);
      }
    }
  }

  private refreshView(): void {
    const depth = this.selectedDepth();
    const aggregationStep = this.selectedAggregation();

    const bids = this.aggregateSide(this.bookState.bids, 'bids', depth, aggregationStep);
    const asks = this.aggregateSide(this.bookState.asks, 'asks', depth, aggregationStep);

    this.bids.set(bids);
    this.asks.set(asks);
    this.maxBidTotal.set(bids.reduce((max, row) => Math.max(max, row.total), 0));
    this.maxAskTotal.set(asks.reduce((max, row) => Math.max(max, row.total), 0));
  }

  private aggregateSide(
    levels: Map<number, number>,
    side: 'bids' | 'asks',
    depth: number,
    aggregationStep: number,
  ): OrderBookRow[] {
    const entries = Array.from(levels.entries()).filter(([, size]) => size > 0);

    if (side === 'bids') {
      entries.sort((a, b) => b[0] - a[0]);
    } else {
      entries.sort((a, b) => a[0] - b[0]);
    }

    const step = aggregationStep > 0 ? aggregationStep : 0;
    const grouped = new Map<number, number>();

    for (const [price, size] of entries) {
      const bucketPrice =
        step > 0
          ? side === 'bids'
            ? this.roundDown(price, step)
            : this.roundUp(price, step)
          : price;

      const existing = grouped.get(bucketPrice) ?? 0;
      grouped.set(bucketPrice, existing + size);
    }

    const groupedEntries = Array.from(grouped.entries());
    if (side === 'bids') {
      groupedEntries.sort((a, b) => b[0] - a[0]);
    } else {
      groupedEntries.sort((a, b) => a[0] - b[0]);
    }

    const limited = groupedEntries.slice(0, depth);

    let runningTotal = 0;
    return limited.map(([price, size]) => {
      runningTotal += size;
      return {
        price: Number(this.formatPriceValue(price)),
        size,
        total: runningTotal,
      };
    });
  }

  private roundDown(price: number, step: number): number {
    const bucket = Math.floor(price / step + 1e-8) * step;
    return Number(bucket.toFixed(this.pricePrecision()));
  }

  private roundUp(price: number, step: number): number {
    const bucket = Math.ceil(price / step - 1e-8) * step;
    return Number(bucket.toFixed(this.pricePrecision()));
  }

  private formatPriceValue(price: number): number {
    return Number(price.toFixed(this.pricePrecision()));
  }

  private resolvePriceDecimals(instrument: Instrument | null): number {
    const tickSize = Number(instrument?.tick_size ?? 0);
    if (Number.isFinite(tickSize) && tickSize > 0) {
      return this.countDecimals(tickSize);
    }
    return 4;
  }

  private countDecimals(value: number): number {
    if (!Number.isFinite(value)) {
      return 0;
    }
    const valueString = value.toString();
    if (!valueString.includes('.')) {
      return 0;
    }
    return valueString.split('.')[1]?.length ?? 0;
  }

  private estimateFallbackStep(instrument: Instrument | null): number {
    if (!instrument) {
      return 1;
    }
    const symbol = instrument.symbol ?? '';
    if (symbol.includes('USD') || symbol.includes('EUR')) {
      return 0.01;
    }
    return 1;
  }

  private formatPrice(value: number): string {
    return this.priceFormatter.format(Number(value.toFixed(this.pricePrecision())));
  }

  private formatTimestamp(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return this.timeFormatter.format(date);
  }
}
