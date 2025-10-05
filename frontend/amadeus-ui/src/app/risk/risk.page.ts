import { Component } from '@angular/core';
import { PagePlaceholderComponent } from '../shared/page-placeholder.component';
import { RiskMetrics } from '../api/models';

@Component({
  standalone: true,
  selector: 'app-risk-page',
  imports: [PagePlaceholderComponent],
  template: `
    <app-page-placeholder
      title="Risk controls"
      description="The risk management console will expose trading locks and limit configuration similar to Amadeus 1.0."
      hint="Implementation pending integration with the gateway risk API."
    ></app-page-placeholder>
  `,
})
export class RiskPage {
  readonly metrics: RiskMetrics | null = null;
}
