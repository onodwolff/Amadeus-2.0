import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export interface MetricsTableRow {
  readonly label: string;
  readonly value: string | number;
  readonly hint?: string;
}

@Component({
  selector: 'app-metrics-table',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './metrics-table.component.html',
  styleUrls: ['./metrics-table.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MetricsTableComponent {
  @Input() rows: readonly MetricsTableRow[] = [];
}
