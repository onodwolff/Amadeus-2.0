import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, ViewChild, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { PortfolioMetricsStore, PortfolioMetricsPeriod } from './portfolio-metrics.store';
import { TimeSeriesChartComponent } from '../../../shared/components/time-series-chart/time-series-chart.component';

@Component({
  selector: 'app-portfolio-metrics-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, TimeSeriesChartComponent],
  templateUrl: './portfolio-metrics-panel.component.html',
  styleUrls: ['./portfolio-metrics-panel.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PortfolioMetricsPanelComponent implements OnInit {
  private readonly currencyFormatterIntl = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  readonly store = inject(PortfolioMetricsStore);

  @ViewChild('dailyChart') private dailyChart?: TimeSeriesChartComponent;
  @ViewChild('realizedChart') private realizedChart?: TimeSeriesChartComponent;
  @ViewChild('exposureChart') private exposureChart?: TimeSeriesChartComponent;

  readonly hasDailyPnl = computed(() => this.store.dailyPnlSeries().length > 0);
  readonly hasRealized = computed(() => this.store.realizedUnrealizedSeries().length > 0);
  readonly hasExposure = computed(() => this.store.exposureSeries().length > 0);

  readonly currencyFormatter = (value: number) => this.currencyFormatterIntl.format(value);

  ngOnInit(): void {
    this.store.loadHistory();
  }

  onPeriodChange(period: PortfolioMetricsPeriod | string): void {
    this.store.setPeriod(period as PortfolioMetricsPeriod);
  }

  exportDailyCsv(): void {
    const rows = this.store.dailyPnlTable();
    if (rows.length === 0) {
      return;
    }
    const data = rows.map(entry => [entry.timestamp, entry.pnl.toFixed(2)]);
    this.downloadCsv('portfolio-daily-pnl.csv', ['Timestamp', 'PnL'], data);
  }

  exportRealizedCsv(): void {
    const rows = this.store.realizedUnrealizedTable();
    if (rows.length === 0) {
      return;
    }
    const data = rows.map(entry => [entry.timestamp, entry.realized.toFixed(2), entry.unrealized.toFixed(2)]);
    this.downloadCsv('portfolio-realized-unrealized.csv', ['Timestamp', 'Realized', 'Unrealized'], data);
  }

  exportExposureCsv(): void {
    const rows = this.store.exposureTable();
    if (rows.length === 0) {
      return;
    }
    const columns = Object.keys(rows[0].values);
    if (columns.length === 0) {
      return;
    }
    const data = rows.map(entry => [entry.timestamp, ...columns.map(column => entry.values[column].toFixed(2))]);
    this.downloadCsv('portfolio-exposure.csv', ['Timestamp', ...columns], data);
  }

  exportDailyPng(): void {
    this.exportChartAsPng(this.dailyChart, 'portfolio-daily-pnl.png');
  }

  exportRealizedPng(): void {
    this.exportChartAsPng(this.realizedChart, 'portfolio-realized-unrealized.png');
  }

  exportExposurePng(): void {
    this.exportChartAsPng(this.exposureChart, 'portfolio-exposure.png');
  }

  private exportChartAsPng(chart: TimeSeriesChartComponent | undefined, filename: string): void {
    const dataUrl = chart?.captureScreenshot();
    if (!dataUrl) {
      return;
    }
    const anchor = document.createElement('a');
    anchor.href = dataUrl;
    anchor.download = filename;
    anchor.click();
    anchor.remove();
  }

  private downloadCsv(filename: string, header: string[], rows: (string | number)[][]): void {
    const csvContent = [header, ...rows]
      .map(line => line.map(value => this.escapeCsv(String(value))).join(','))
      .join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    link.remove();
  }

  private escapeCsv(value: string): string {
    if (/[,"\n]/.test(value)) {
      return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
  }
}
