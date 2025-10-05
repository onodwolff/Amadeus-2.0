import { Component } from '@angular/core';
import { PagePlaceholderComponent } from '../shared/page-placeholder.component';

@Component({
  standalone: true,
  selector: 'app-backtest-page',
  imports: [PagePlaceholderComponent],
  template: `
    <app-page-placeholder
      title="Backtests"
      description="Configure and launch historical simulations. The detailed configuration form from Amadeus 1.0 will be ported in a dedicated task."
      hint="For now, use the controls on the Nodes page to launch a default backtest node."
    ></app-page-placeholder>
  `,
})
export class BacktestPage {}
