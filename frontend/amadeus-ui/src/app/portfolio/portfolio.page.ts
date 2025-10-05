import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  standalone: true,
  selector: 'app-portfolio-page',
  imports: [CommonModule],
  template: `
    <section class="page-placeholder">
      <h1>Portfolio</h1>
      <p>Real-time balances, positions and fills will appear here as we complete the migration from Amadeus 1.0.</p>
      <p class="hint">Coming soon: streaming fills from Nautilus Trader sessions and aggregated account metrics.</p>
    </section>
  `,
  styles: [`
    .page-placeholder { display: grid; gap: 12px; padding: 24px; border-radius: 16px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(148, 163, 184, 0.16); }
    h1 { margin: 0; font-size: 1.75rem; }
    .hint { color: rgba(148, 163, 184, 0.9); font-style: italic; }
  `],
})
export class PortfolioPage {}
