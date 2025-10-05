import { Component } from '@angular/core';
import { PagePlaceholderComponent } from '../shared/page-placeholder.component';
import { PortfolioSummary } from '../api/models';

@Component({
  standalone: true,
  selector: 'app-portfolio-page',
  imports: [PagePlaceholderComponent],
  template: `
    <app-page-placeholder
      title="Portfolio"
      description="Real-time balances, positions and fills will appear here as we complete the migration from Amadeus 1.0."
      hint="Coming soon: streaming fills from Nautilus Trader sessions and aggregated account metrics."
    ></app-page-placeholder>
  `,
})
export class PortfolioPage {
  readonly portfolio: PortfolioSummary | null = null;
}
