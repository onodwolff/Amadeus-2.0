import { CommonModule } from '@angular/common';
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import {
  ColorType,
  IChartApi,
  ISeriesApi,
  LineData,
  LineSeriesPartialOptions,
  UTCTimestamp,
  createChart,
} from 'lightweight-charts';

export interface TimeSeriesPoint {
  timestamp: string;
  value: number;
}

export interface TimeSeriesChartSeries {
  readonly id: string;
  readonly name: string;
  readonly color: string;
  readonly data: readonly TimeSeriesPoint[];
}

@Component({
  selector: 'app-time-series-chart',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './time-series-chart.component.html',
  styleUrls: ['./time-series-chart.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimeSeriesChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input() series: readonly TimeSeriesChartSeries[] = [];
  @Input() valueFormatter: (value: number) => string = value => value.toFixed(2);

  @ViewChild('container', { static: true }) private readonly container?: ElementRef<HTMLDivElement>;

  private chart: IChartApi | null = null;
  private seriesMap = new Map<string, ISeriesApi<'Line'>>();
  private resizeObserver: ResizeObserver | null = null;

  readonly trackById = (_: number, item: TimeSeriesChartSeries) => item.id;

  ngAfterViewInit(): void {
    this.initializeChart();
    this.updateSeries();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['series'] && this.chart) {
      this.updateSeries();
    }
    if (changes['valueFormatter'] && this.chart) {
      this.chart.applyOptions({
        localization: {
          priceFormatter: this.valueFormatter,
        },
      });
    }
  }

  ngOnDestroy(): void {
    this.disposeChart();
  }

  private initializeChart(): void {
    if (!this.container) {
      return;
    }
    const element = this.container.nativeElement;
    this.chart = createChart(element, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#cbd5f5',
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.12)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.12)' },
      },
      rightPriceScale: {
        visible: true,
        borderColor: 'rgba(148, 163, 184, 0.18)',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.18)',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        horzLine: { color: 'rgba(148, 163, 184, 0.3)', labelBackgroundColor: 'rgba(30, 64, 175, 0.6)' },
        vertLine: { color: 'rgba(148, 163, 184, 0.3)', labelBackgroundColor: 'rgba(30, 64, 175, 0.6)' },
      },
      localization: {
        priceFormatter: this.valueFormatter,
      },
    });
    const { clientWidth, clientHeight } = element;
    this.chart.applyOptions({ width: clientWidth, height: clientHeight });

    this.resizeObserver = new ResizeObserver(() => {
      if (this.chart && this.container) {
        const { clientWidth: width, clientHeight: height } = this.container.nativeElement;
        this.chart.applyOptions({ width, height });
      }
    });
    this.resizeObserver.observe(element);
  }

  private disposeChart(): void {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    for (const series of this.seriesMap.values()) {
      this.chart?.removeSeries(series);
    }
    this.seriesMap.clear();
    this.chart?.remove();
    this.chart = null;
  }

  private updateSeries(): void {
    if (!this.chart) {
      return;
    }

    const nextIds = new Set(this.series.map(entry => entry.id));
    for (const [id, series] of this.seriesMap.entries()) {
      if (!nextIds.has(id)) {
        this.chart.removeSeries(series);
        this.seriesMap.delete(id);
      }
    }

    for (const entry of this.series) {
      const existing = this.seriesMap.get(entry.id);
      const options: LineSeriesPartialOptions = {
        color: entry.color,
        lineWidth: 2,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: true,
      };
      const target = existing ?? this.chart.addLineSeries(options);
      if (!existing) {
        this.seriesMap.set(entry.id, target);
      } else {
        target.applyOptions(options);
      }
      const data = this.transformData(entry.data);
      target.setData(data);
    }

    if (this.series.length > 0) {
      this.chart.timeScale().fitContent();
    }
  }

  private transformData(data: readonly TimeSeriesPoint[]): LineData[] {
    return data
      .filter(point => typeof point.value === 'number' && !Number.isNaN(point.value))
      .map(point => ({
        time: (Math.floor(Date.parse(point.timestamp) / 1000) as UTCTimestamp) ?? 0,
        value: point.value,
      }));
  }

  captureScreenshot(): string | null {
    if (!this.chart) {
      return null;
    }
    const screenshot = (this.chart as any).takeScreenshot?.();
    if (screenshot instanceof HTMLCanvasElement) {
      return screenshot.toDataURL('image/png');
    }
    if (screenshot && typeof screenshot.toDataURL === 'function') {
      return screenshot.toDataURL('image/png');
    }
    return null;
  }
}
