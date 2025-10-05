import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { map } from 'rxjs';

@Component({
  standalone: true,
  selector: 'app-backtest-detail-page',
  imports: [CommonModule],
  templateUrl: './backtest-detail.page.html',
  styleUrls: ['./backtest-detail.page.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BacktestDetailPage {
  private readonly route = inject(ActivatedRoute);

  readonly runId$ = this.route.paramMap.pipe(map(params => params.get('runId')));
}
