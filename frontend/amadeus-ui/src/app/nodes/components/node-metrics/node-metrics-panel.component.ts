import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  computed,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MetricsChartComponent, MetricsChartSeries } from '../metrics-chart/metrics-chart.component';
import { NodeMetricsStore, NodeMetricCard, NodeMetricsPeriod } from './node-metrics.store';
import { NodeMetricKey } from '../../../api/models';

@Component({
  selector: 'app-node-metrics-panel',
  standalone: true,
  imports: [CommonModule, MetricsChartComponent],
  templateUrl: './node-metrics-panel.component.html',
  styleUrls: ['./node-metrics-panel.component.scss'],
  providers: [NodeMetricsStore],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodeMetricsPanelComponent implements OnChanges, OnDestroy {
  @Input() nodeId: string | null = null;

  private readonly store = inject(NodeMetricsStore);

  readonly streamState = this.store.streamState;
  readonly period = this.store.period;
  readonly periodOptions = this.store.periodOptions;
  readonly metricDefinitions = this.store.metricDefinitions;
  readonly cards = this.store.cards;
  readonly chartSeries = this.store.chartSeries;

  readonly hasSeries = computed(() => this.chartSeries().length > 0);

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['nodeId']) {
      const id = this.nodeId;
      if (typeof id === 'string' && id.length > 0) {
        this.store.connect(id);
      } else {
        this.store.disconnect();
      }
    }
  }

  ngOnDestroy(): void {
    this.store.disconnect();
  }

  onSelectPeriod(option: NodeMetricsPeriod): void {
    this.store.setPeriod(option);
  }

  onToggleMetric(key: NodeMetricKey): void {
    this.store.toggleMetric(key);
  }

  trackCard = (_: number, card: NodeMetricCard) => card.key;
  trackSeries = (_: number, series: MetricsChartSeries) => series.id;

  metricSelected(key: NodeMetricKey): boolean {
    return this.store.metricSelected(key);
  }
}
