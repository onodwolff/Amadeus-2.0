import {
  Component,
  ElementRef,
  Input,
  OnChanges,
  OnDestroy,
  OnInit,
  SimpleChanges,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  CandlestickData,
  HistogramData,
  IChartApi,
  IPriceScaleApi,
  ISeriesApi,
  LineData,
  PriceScaleMode,
  UTCTimestamp,
  createChart,
} from 'lightweight-charts';
import { Instrument } from '../../../api/models';
import { PriceChartDataService } from './price-chart-data.service';
import { MarketBar, MarketTick } from '../../../api/models';
import { Subscription, take } from 'rxjs';
import { WsConnectionState } from '../../../ws.service';

export type PriceChartIndicator = 'none' | 'sma' | 'ema';
export type PriceChartScale = 'linear' | 'log' | 'percent';

@Component({
  selector: 'app-price-chart',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './price-chart.component.html',
  styleUrls: ['./price-chart.component.scss'],
})
export class PriceChartComponent implements OnInit, OnChanges, OnDestroy {
  @Input() instrument: Instrument | null = null;
  @Input() timeframe = '1h';
  @Input() indicator: PriceChartIndicator = 'none';
  @Input() priceScale: PriceChartScale = 'linear';

  @ViewChild('chartContainer', { static: true })
  private chartContainer?: ElementRef<HTMLDivElement>;

  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly wsState = signal<WsConnectionState>('disconnected');
  readonly lastUpdated = signal<string | null>(null);
  readonly hasData = computed(() => this.candles.length > 0);

  private readonly dataService = inject(PriceChartDataService);

  private chart: IChartApi | null = null;
  private priceScaleApi: IPriceScaleApi | null = null;
  private candlestickSeries: ISeriesApi<'Candlestick'> | null = null;
  private volumeSeries: ISeriesApi<'Histogram'> | null = null;
  private indicatorSeries: ISeriesApi<'Line'> | null = null;
  private resizeObserver?: ResizeObserver;

  private barsSubscription?: Subscription;
  private tickSubscription?: Subscription;
  private stateSubscription?: Subscription;

  private candles: CandlestickData[] = [];
  private volumes: HistogramData[] = [];

  ngOnInit(): void {
    this.initializeChart();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['priceScale'] && !changes['priceScale'].firstChange) {
      this.applyPriceScaleMode();
    }

    if (changes['indicator'] && !changes['indicator'].firstChange) {
      this.updateIndicatorSeries();
    }

    if (changes['instrument'] || changes['timeframe']) {
      const hasInstrument = !!this.instrument;
      if (hasInstrument) {
        this.reloadData();
      } else {
        this.clearData();
      }
    }
  }

  ngOnDestroy(): void {
    this.teardownStreams();
    this.barsSubscription?.unsubscribe();
    this.barsSubscription = undefined;
    this.resizeObserver?.disconnect();
    this.chart?.remove();
    this.chart = null;
    this.priceScaleApi = null;
    this.candlestickSeries = null;
    this.volumeSeries = null;
    this.indicatorSeries = null;
  }

  private initializeChart(): void {
    if (this.chart) {
      return;
    }
    const host = this.chartContainer?.nativeElement;
    if (!host) {
      return;
    }

    const initialWidth = host.clientWidth || host.offsetWidth || 600;
    const initialHeight = host.clientHeight || host.offsetHeight || 360;

      this.chart = createChart(host, {
        width: initialWidth,
        height: initialHeight,
        layout: {
          background: { color: 'transparent' },
          textColor: '#1f2937',
        },
      rightPriceScale: { borderVisible: false },
      timeScale: {
        borderVisible: false,
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.2)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.2)' },
      },
      crosshair: {
        horzLine: { visible: true, labelVisible: true },
        vertLine: { visible: true, labelVisible: true },
      },
    });

    this.priceScaleApi = this.chart.priceScale('right');

    this.candlestickSeries = this.chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      borderVisible: false,
    });

      this.volumeSeries = this.chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
        color: '#94a3b8',
      });

      const volumeScale = this.chart.priceScale('volume');
      volumeScale.applyOptions({
        scaleMargins: {
          top: 0.8,
          bottom: 0,
        },
      });

    this.applyPriceScaleMode();

    this.resizeObserver = new ResizeObserver((entries) => {
      if (!this.chart) {
        return;
      }
      const entry = entries[0];
      if (!entry) {
        return;
      }
      const { width, height } = entry.contentRect;
      this.chart.applyOptions({ width, height });
      this.chart.timeScale().fitContent();
    });
    this.resizeObserver.observe(host);
  }

  private reloadData(): void {
    if (!this.instrument) {
      return;
    }

    this.initializeChart();
    this.fetchHistoricalBars();
    this.subscribeToTicks();
  }

  private fetchHistoricalBars(): void {
    if (!this.instrument) {
      return;
    }
    this.isLoading.set(true);
    this.error.set(null);

    this.barsSubscription?.unsubscribe();
    this.barsSubscription = this.dataService
      .loadHistoricalBars(this.instrument.instrument_id, this.timeframe, { limit: 500 })
      .pipe(take(1))
      .subscribe({
        next: (response) => this.onBarsLoaded(response.bars ?? []),
        error: (error) => {
          console.error(error);
          this.isLoading.set(false);
          this.error.set('Failed to load historical price data.');
          this.clearData();
        },
      });
  }

  private onBarsLoaded(bars: MarketBar[]): void {
    const sorted = [...bars].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
    );

    this.candles = sorted.map((bar) => this.toCandle(bar));
    this.volumes = sorted.map((bar) => this.toVolumeBar(bar));

    this.candlestickSeries?.setData(this.candles);
    this.volumeSeries?.setData(this.volumes);

    this.updateIndicatorSeries();
    this.chart?.timeScale().fitContent();

    const last = sorted.at(-1);
    this.lastUpdated.set(last ? last.timestamp : null);
    this.isLoading.set(false);
  }

  private subscribeToTicks(): void {
    if (!this.instrument) {
      return;
    }

    this.teardownStreams();
    this.wsState.set('connecting');

    const channel = this.dataService.openTickStream(this.instrument.instrument_id);
    this.tickSubscription = channel.messages$.subscribe((tick) => this.onTick(tick));
    this.stateSubscription = channel.state$.subscribe((state) => this.wsState.set(state));
  }

  private onTick(tick: MarketTick): void {
    if (!this.instrument || tick.instrument_id !== this.instrument.instrument_id) {
      return;
    }

    const bucket = this.resolveBucketTimestamp(tick.timestamp);
    if (bucket === null) {
      return;
    }

    const current = this.candles.at(-1);
    if (!current || (current.time as number) < bucket) {
      const newCandle: CandlestickData = {
        time: bucket as UTCTimestamp,
        open: tick.price,
        high: tick.price,
        low: tick.price,
        close: tick.price,
      };
      this.candles = [...this.candles, newCandle];
      this.candlestickSeries?.update(newCandle);

      const newVolume: HistogramData = {
        time: bucket as UTCTimestamp,
        value: tick.volume ?? 0,
        color: '#94a3b8',
      };
      this.volumes = [...this.volumes, newVolume];
      this.volumeSeries?.update(newVolume);
    } else if ((current.time as number) === bucket) {
      const updated: CandlestickData = {
        time: current.time,
        open: current.open,
        high: Math.max(current.high, tick.price),
        low: Math.min(current.low, tick.price),
        close: tick.price,
      };
      this.candles = [...this.candles.slice(0, -1), updated];
      this.candlestickSeries?.update(updated);

      const previousVolume = this.volumes.at(-1);
      const updatedVolume: HistogramData = {
        time: bucket as UTCTimestamp,
        value: (previousVolume?.value ?? 0) + (tick.volume ?? 0),
        color: tick.price >= updated.open ? '#26a69a' : '#ef5350',
      };
      this.volumes = [...this.volumes.slice(0, -1), updatedVolume];
      this.volumeSeries?.update(updatedVolume);
    }

    this.updateIndicatorSeries();
    this.lastUpdated.set(tick.timestamp);
  }

  private updateIndicatorSeries(): void {
    if (!this.chart || !this.candlestickSeries) {
      return;
    }

    if (this.indicator === 'none' || this.candles.length === 0) {
      if (this.indicatorSeries) {
        this.indicatorSeries.setData([]);
      }
      return;
    }

    const data =
      this.indicator === 'sma'
        ? this.calculateSma(this.candles, 20)
        : this.calculateEma(this.candles, 20);

    const color = this.indicator === 'sma' ? '#2563eb' : '#7c3aed';

    if (!this.indicatorSeries) {
      this.indicatorSeries = this.chart.addLineSeries({
        color,
        lineWidth: 2,
      });
    } else {
      this.indicatorSeries.applyOptions({ color });
    }

    this.indicatorSeries.setData(data);
  }

  private applyPriceScaleMode(): void {
    if (!this.priceScaleApi) {
      return;
    }
    const mode = this.resolveScaleMode(this.priceScale);
    this.priceScaleApi.applyOptions({ mode });
  }

  private clearData(): void {
    this.candles = [];
    this.volumes = [];
    this.candlestickSeries?.setData([]);
    this.volumeSeries?.setData([]);
    this.indicatorSeries?.setData([]);
    this.lastUpdated.set(null);
    this.error.set(null);
    this.isLoading.set(false);
  }

  private teardownStreams(): void {
    this.tickSubscription?.unsubscribe();
    this.stateSubscription?.unsubscribe();
    this.tickSubscription = undefined;
    this.stateSubscription = undefined;
    this.wsState.set('disconnected');
  }

  private toCandle(bar: MarketBar): CandlestickData {
    return {
      time: this.toTimestamp(bar.timestamp),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    };
  }

  private toVolumeBar(bar: MarketBar): HistogramData {
    const time = this.toTimestamp(bar.timestamp);
    const color = bar.close >= bar.open ? '#26a69a' : '#ef5350';
    return {
      time,
      value: bar.volume ?? 0,
      color,
    };
  }

  private toTimestamp(timestamp: string): UTCTimestamp {
    return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
  }

  private resolveBucketTimestamp(timestamp: string): number | null {
    const timeframeSeconds = this.timeframeToSeconds(this.timeframe);
    if (!timeframeSeconds) {
      return null;
    }
    const milliseconds = new Date(timestamp).getTime();
    if (Number.isNaN(milliseconds)) {
      return null;
    }
    const seconds = Math.floor(milliseconds / 1000);
    return Math.floor(seconds / timeframeSeconds) * timeframeSeconds;
  }

  private timeframeToSeconds(value: string): number | null {
    const match = /^(\d+)([smhdw])$/i.exec(value);
    const amountRaw = match?.[1] ?? '';
    const unit = match?.[2]?.toLowerCase() ?? '';
    if (!amountRaw || !unit) {
      return null;
    }
    const amount = Number(amountRaw);
    if (!Number.isFinite(amount)) {
      return null;
    }
    const factor: Record<string, number> = {
      s: 1,
      m: 60,
      h: 60 * 60,
      d: 60 * 60 * 24,
      w: 60 * 60 * 24 * 7,
    };
    const multiplier = factor[unit];
    return multiplier ? amount * multiplier : null;
  }

  private resolveScaleMode(scale: PriceChartScale): PriceScaleMode {
    switch (scale) {
      case 'log':
        return PriceScaleMode.Logarithmic;
      case 'percent':
        return PriceScaleMode.Percentage;
      default:
        return PriceScaleMode.Normal;
    }
  }

  private calculateSma(candles: CandlestickData[], period: number): LineData[] {
    const result: LineData[] = [];
    const queue: number[] = [];
    let sum = 0;
    for (const candle of candles) {
      queue.push(candle.close);
      sum += candle.close;
      if (queue.length > period) {
        sum -= queue.shift() ?? 0;
      }
      if (queue.length === period) {
        result.push({ time: candle.time, value: sum / period });
      }
    }
    return result;
  }

  private calculateEma(candles: CandlestickData[], period: number): LineData[] {
    const result: LineData[] = [];
    if (candles.length === 0) {
      return result;
    }
    const k = 2 / (period + 1);
    let previousEma: number | null = null;
    let index = 0;
    for (const candle of candles) {
      if (previousEma === null) {
        previousEma = candle.close;
      } else {
        previousEma = candle.close * k + previousEma * (1 - k);
      }
      index += 1;
      if (index >= period) {
        result.push({ time: candle.time, value: previousEma });
      }
    }
    return result;
  }
}
